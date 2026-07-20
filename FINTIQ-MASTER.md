# FINTIQ MASTER PROJECT DOCUMENT
*Last updated: 20 July 2026 — paste this into Claude at the start of every new session*

---

## 1. WHO IS IMRAN

**Name:** Imran Khakwani
**Email:** imran.khakwany@gmail.com
**Location:** London, United Kingdom

**Professional background:**
- 16+ years in finance
- Started at KPMG Pakistan (1997) and EY Pakistan as auditor
- Senior Accountant at Berkeley Accountants London (June 2012 – present)
- CFO at Sedel Capital (digital banking startup, 2016–2018)
- Finance Manager at Rizq Financial Technology (fintech, 2022)
- MLRO at RZQ Finance (2023–2024)

**Qualifications:**
- FCA (Fellow Chartered Accountant) — ICAP Pakistan
- MSc Finance & Investment — BPP Business School, London
- CISI Level 4 Diploma in Investment Advice & Financial Planning (2025)
- ACSI (2025)

**Interests:** Golf, café culture, writes blogs on taxation and personal finance

---

## 2. WHAT IS FINTIQ

**Fintiq** is a professional-grade investment analysis platform for retail investors. The founding insight: retail investors lose money not because markets are against them, but because they never had a method. They speculate instead of invest.

**Mission:** Give retail investors the same analytical tools used by institutional fund managers — without requiring a Bloomberg terminal, a finance degree, or years of experience.

**Founding story:** Imran saw people around him (including himself) go into trading with enthusiasm but lose money because they didn't know WHY they were buying or selling. They had no method. Fintiq gives retail investors a systematic, professional-grade investment methodology.

**Target audience:** UK retail investors primarily, expanding to US investors

---

## 3. TECH STACK & INFRASTRUCTURE

**Landing site:** fintiq.uk (static HTML/CSS/JS — no framework)
- Hosted on: Vercel
- GitHub repo: https://github.com/imrankhakwani-oss/fintiq-landing
- Branch: main (auto-deploys to Vercel on push)

**App:** app.fintiq.uk (separate codebase — not in Articles folder)

**Analytics:** Google Analytics 4 — Tag ID: G-SFD342RVKK
- GA tag added to ALL pages (index.html, learn.html, tools.html, monte-carlo-retirement.html, all 20 learn/ articles)

**Payments:** Stripe (integrated on pro article pages)
- Individual pro article: £2.50
- Pro bundle (all 6): £10.00
- Stripe links on each pro article page

**Google Search Console:** Submitted, sitemap resubmitted 18 July 2026
- URL Inspection / Request Indexing done for tools.html and monte-carlo-retirement.html

---

## 4. FILE STRUCTURE — LANDING SITE

All files live at: `C:\Users\imran\Desktop\Fintiq\Articles\`

```
Articles/
├── index.html                          ← Main landing page
├── learn.html                          ← Learn hub (all 20 guides listed)
├── tools.html                          ← Free Tools hub page
├── monte-carlo-retirement.html         ← Retirement Monte Carlo simulator
├── sitemap.xml                         ← Full sitemap (24 pages)
├── FINTIQ-MASTER.md                    ← This document
├── Imran-LinkedIn-Profile.md           ← LinkedIn profile copy
├── LinkedIn-Posts-20-Days.md           ← 20 ready-to-post LinkedIn posts
├── Reddit-Strategy-Fintiq.md          ← Reddit strategy document
└── learn/
    ├── what-is-a-stock-screener.html
    ├── key-financial-metrics.html
    ├── what-is-monte-carlo-simulation.html
    ├── how-to-read-rsi-macd.html
    ├── ftse-100-vs-nasdaq.html
    ├── what-is-portfolio-diversification.html
    ├── isa-vs-sipp.html
    ├── screen-stocks-like-hedge-fund.html
    ├── monte-carlo-retirement-planning.html
    ├── efficient-frontier-mpt.html
    ├── sharpe-ratio-portfolio.html
    ├── cointegration-explained.html
    ├── broker-comparison-uk.html
    ├── dcf-model-fintiq.html
    ├── ftse-100-screening-masterclass.html        ← Pro (gated)
    ├── efficient-frontier-step-by-step.html       ← Pro (gated)
    ├── monte-carlo-fire-strategy.html             ← Pro (gated)
    ├── pairs-trading-cointegration-guide.html     ← Pro (gated)
    ├── advanced-technical-analysis.html           ← Pro (gated)
    ├── fund-manager-portfolio-construction.html   ← Pro (gated)
    ├── ftse-100-screening-masterclass-unlocked.html
    ├── efficient-frontier-step-by-step-unlocked.html
    ├── monte-carlo-fire-strategy-unlocked.html
    ├── pairs-trading-cointegration-guide-unlocked.html
    ├── advanced-technical-analysis-unlocked.html
    ├── fund-manager-portfolio-construction-unlocked.html
    └── pro-bundle-unlocked.html
```

---

## 5. CONTENT — WHAT'S BEEN BUILT

### Free Articles (14 total)
**Foundation (7):**
1. What is a Stock Screener and Why Every Investor Needs One
2. P/E Ratio, ROE, and the 5 Key Metrics Every Investor Must Know
3. What is Monte Carlo Simulation? A Simple Guide for Investors
4. How to Read RSI and MACD: Technical Analysis for Beginners
5. FTSE 100 vs NASDAQ: Which Market Should UK Investors Focus On?
6. What is Portfolio Diversification and How Do You Actually Do It?
7. ISA vs SIPP: Where Should Your Investments Live?

**Intermediate (7):**
8. How to Screen FTSE 100 Stocks Like a Hedge Fund Manager
9. Using Monte Carlo Simulation to Plan Your Retirement
10. What is the Efficient Frontier? Modern Portfolio Theory Explained
11. How to Build a Balanced Portfolio Using the Sharpe Ratio
12. Cointegration Explained: The Strategy Institutional Traders Use
13. Hargreaves Lansdown vs AJ Bell vs Trading 212 vs Freetrade: Which is Best?
14. How to Use the DCF Financial Model in Fintiq to Value Any Company

### Pro Articles (6 total — £2.50 each or £10 bundle)
1. Complete FTSE 100 Stock Screening Masterclass
2. Building Your Optimal Portfolio with the Efficient Frontier — Step by Step
3. Monte Carlo Simulation for FIRE and Early Retirement Planning
4. Pairs Trading with Cointegration: A Practical Guide
5. Advanced Technical Analysis: Combining RSI, MACD and Momentum
6. How Professional Fund Managers Construct Portfolios — and How to Copy Them

### Free Tools (built as standalone pages)
1. **Retirement Monte Carlo Simulator** (fintiq.uk/monte-carlo-retirement.html)
   - UK and US modes (State Pension / Social Security)
   - 5,000 simulations using Box-Muller random normal distribution
   - Fan chart (10th, 25th, 50th, 75th, 90th percentile)
   - Success rate, median outcome, best/worst decile stats
   - Personalised insights based on inputs
   - Built with Chart.js from CDN
   - No sign-up required

**Coming soon (listed on tools.html):**
- ISA vs SIPP Calculator
- FIRE Number Calculator
- Dividend Income Planner
- Drawdown Risk Analyser

---

## 6. NAVIGATION STRUCTURE

**Main nav (index.html):** Features | How it works | Pricing | Free Tools | Learn | FAQ | Launch App →

**Learn nav:** Free Tools | Learn | Try the App →

**Tools nav:** Free Tools (active) | Learn | Stock Screener →

**Retirement simulator nav:** ← Free Tools | Learn | Stock Screener →

---

## 7. BUSINESS MODEL

**Freemium:**
- Free: landing site, all 14 free articles, all app tools (screener, Monte Carlo, portfolio optimiser, pairs trading, DCF, technical analysis), retirement simulator
- Paid: 6 Pro articles at £2.50 each or £10 bundle via Stripe

**Revenue streams to develop:**
- Pro article sales (Stripe — live)
- Future: Pro app subscription tier
- Future: Premium tools

---

## 8. SEO STATUS

**Google Analytics:** Live, tag G-SFD342RVKK on all pages
**Google Search Console:** Verified, sitemap submitted
**Sitemap:** fintiq.uk/sitemap.xml (24 pages)
**Pages indexed as of 20 July 2026:** 2 (site very new, crawling in progress)
**Request Indexing submitted for:** tools.html, monte-carlo-retirement.html

**Key SEO pages to rank:**
- "Monte Carlo retirement calculator UK"
- "Free stock screener UK"
- "ISA vs SIPP"
- "FTSE 100 stock screener"
- "Retirement Monte Carlo simulation UK"

---

## 9. SOCIAL MEDIA

### LinkedIn (Personal — Imran)
**Profile URL:** https://www.linkedin.com/in/imran-khakwani-acsi-fca-41185710/
**Headline updated to:** Founder @ Fintiq 📊 | Giving Retail Investors the Tools Professional Traders Use | CISI Level 4 Diploma | Senior Accountant (FCA) | Wealth Planning and Investing
**About section:** Updated with founding story
**Featured:** fintiq.uk and learn.html pinned
**Connections:** 405

**Content plan:** 20 LinkedIn posts written (LinkedIn-Posts-20-Days.md)
- Days 1–14: Free articles (pure value, no selling)
- Days 15–20: Pro article teasers
- Post daily, best times: Tue–Thu 8–9am or 12–1pm
- Reply to ALL comments within 60 minutes

### Reddit
**Account:** u/trader1311
**Joined subreddits:** r/UKInvesting, r/ukpersonalfinance, r/FIREUK, r/investing, r/beginnerinvesting
**Status:** Account created 20 July 2026, first 4 answers posted
**Strategy:** 1 hour/day — build karma with helpful answers first, post own content once karma established
**DO NOT:** Post links to fintiq.uk until 10+ karma established and username is recognised

**Reddit posts written and ready (Reddit-Strategy-Fintiq.md):**
1. FTSE 100 screening post (r/UKInvesting)
2. Monte Carlo retirement simulation post (r/FIREUK)
3. ISA vs SIPP framework post (r/ukpersonalfinance)
4. Correlation/diversification post (r/UKInvesting)
5. DCF valuation post (r/ValueInvesting)

### Twitter/X, Instagram
- Not yet set up — next phase

---

## 10. APP (app.fintiq.uk) — FULL TECHNICAL DETAILS

### Tech Stack
- **Language:** Python 3.12
- **Framework:** Streamlit (>=1.41.0)
- **Deployment:** Railway (Procfile-based)
- **GitHub repo:** https://github.com/imrankhakwani-oss/fintiq (main branch)
- **Auth:** Supabase (email/password login + signup)
- **Payments:** Stripe subscription (monthly + annual price IDs)
- **Data:** yfinance (market data) + Financial Modeling Prep API (FMP_KEY in code)
- **Charts:** Plotly
- **Database:** SQLite (fintiq_journal.db — trading journal)
- **Watchlist:** JSON file persistence (fintiq_watchlist.json, fintiq_pairs_watchlist.json)

### Main File
- `fintiq_screener.py` — single main app file (2,136 lines, v3.0)
- `_counter.py` — separate counter module + Supabase schema
- `_opt_tail.py` — Portfolio Optimizer (frontier/blurred preview)
- `config.toml` — Streamlit config + Stripe subscription gate
- `.streamlit/` — Streamlit dark theme config
- `fintiq_requirements.txt` — pinned package versions

### Key Dependencies
```
streamlit>=1.41.0
pandas>=2.2.0
numpy>=1.26.0
yfinance>=0.2.54
plotly>=5.22.0
statsmodels>=0.14.0
scipy>=1.11.0
supabase>=2.10.0
stripe>=10.0.0
```

### Environment Variables (Railway)
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_KEY` — Supabase anon key
- `SUPABASE_SERVICE_KEY` — Supabase service role key (admin, bypasses RLS)
- `STRIPE_SECRET_KEY` — Stripe secret key
- `STRIPE_PUBLISHABLE_KEY` — Stripe publishable key
- FMP API key is hardcoded in file: `FMP_KEY = "c3gRy6dPp8uETaNIYoFJj83J7hm998bB"`

### Stripe Subscription
- Monthly price ID: `price_1Tt8fXFSQ5tKKNExQf7T2t92`
- Annual price ID: `price_1Tt8fXFSQ5tKKNExXuntkPsI`
- App URL for redirects: `https://fintiq.uk`

### App Features (v3.0)
1. **Authentication wall** — Supabase email/password login + signup. All features gated behind login.
2. **Multi-factor Stock Screener (Strategy 1 — Quality Value)**
   - Markets: LSE (FTSE 100 + FTSE 250 + AIM), NYSE, NASDAQ, XETRA (DAX), Euronext (CAC40/AEX/BEL20/IBEX), TSX, ASX, NSE (India), HKEX
   - 10 exchanges total, 1000+ stocks in universe
   - Screens on: P/E, ROE, revenue growth, debt/equity, free cash flow, EPS growth, market cap, dividend yield
   - Quality Score: composite 0–100 ranking
   - Currency-aware: £ for LSE/AIM, $ for NYSE/NASDAQ, € for XETRA/Euronext, etc.
   - LSE/AIM stocks: prices in pence (GBp) with dual £/p display
3. **Catalyst Alerts (Strategy 2)**
   - Monitors for technical/fundamental triggers
4. **Pairs Trading (Strategy 3)**
   - Preset pairs across UK, US, Europe, Asia (40+ pairs pre-built)
   - UK pairs: Shell/BP, Lloyds/Barclays, AZN/GSK, Tesco/Sainsbury's, etc.
   - US pairs: JPM/BAC, AAPL/MSFT, KO/PEP, XOM/CVX, etc.
   - European pairs: SAP/SIE, BMW/VOW3, LVMH/Hermès, etc.
   - Custom pair input supported
   - Cointegration test (ADF), Z-score, half-life calculation
   - Pairs watchlist (JSON persistence)
5. **Intrinsic Value / DCF Calculator**
   - Full DCF with WACC, terminal growth, margin assumptions
6. **Trading Journal**
   - SQLite database (fintiq_journal.db)
   - Track trades: date, ticker, direction, strategy, entry/exit price, shares, P&L, notes
   - Status tracking: open/closed
7. **Portfolio Optimiser** (in _opt_tail.py)
   - Efficient Frontier / MPT
   - Blurred preview for non-subscribers
8. **Technical Analysis**
   - RSI, MACD, Bollinger Bands, ATR, EMA
   - Plotly charts
9. **Watchlist**
   - JSON persistence (fintiq_watchlist.json)

### Auth Flow
- New users: sign up with email/password → Supabase creates account
- Existing users: login → session stored in st.session_state
- `is_pro` flag loaded from Supabase profile on every login
- Admin client uses service role key to bypass Row Level Security for profile reads/writes

### Subscription Gate
- Free users: access screener, basic features
- Pro users (Stripe subscriber): full access including Portfolio Optimiser, advanced features
- `is_pro` stored in Supabase user profile
- Stripe webhook updates `is_pro` on subscription events

**Important:** The retirement Monte Carlo (monte-carlo-retirement.html) is on the landing site, NOT in the app — deliberate decision to keep it as a free public traffic-driving tool.

---

## 11. COMPLETED WORK HISTORY

- ✅ index.html built and live
- ✅ Learn nav link added to index.html
- ✅ 20 articles written and published (14 free + 6 pro teasers)
- ✅ 6 unlocked pro article pages built
- ✅ pro-bundle-unlocked.html built
- ✅ Stripe payment links integrated (£2.50 / £10)
- ✅ Google Analytics tag added to ALL pages
- ✅ tools.html built (Free Tools hub)
- ✅ monte-carlo-retirement.html built (full interactive simulator)
- ✅ sitemap.xml built with all 24 pages
- ✅ All files pushed to GitHub (fintiq-landing repo)
- ✅ Google Search Console verified and sitemap submitted
- ✅ LinkedIn profile headline updated
- ✅ LinkedIn featured section added
- ✅ LinkedIn profile document written (Imran-LinkedIn-Profile.md)
- ✅ 20 LinkedIn posts written (LinkedIn-Posts-20-Days.md)
- ✅ Reddit strategy written (Reddit-Strategy-Fintiq.md)
- ✅ Reddit account created (u/trader1311)
- ✅ First Reddit answers posted

---

## 12. NEXT STEPS (IN PRIORITY ORDER)

1. **Reddit daily (1 hour/day):** Answer 3–4 questions per day to build karma. Once 20+ karma, start posting own content from Reddit-Strategy-Fintiq.md
2. **LinkedIn daily (15 mins):** Post one post from LinkedIn-Posts-20-Days.md. Reply to all comments within 60 mins.
3. **Build next free tool:** ISA vs SIPP Calculator (listed as coming soon on tools.html)
4. **Twitter/X:** Set up Fintiq brand account and personal account
5. **Important feature to add to app:** (Imran to specify — mentioned at end of 20 July session)
6. **Update LinkedIn experience:** Add Fintiq Founder & CEO role per Imran-LinkedIn-Profile.md
7. **Create Fintiq LinkedIn company page**
8. **Monitor Google Search Console:** Check weekly for indexed pages and search queries

---

## 13. IMPORTANT RULES FOR CLAUDE

When starting a new session, read this document first, then:

- **Never suggest submitting sitemap** — already done
- **Never suggest adding GA** — already on all pages
- **Never suggest creating articles** — 20 already exist
- **Stripe is already integrated** — don't suggest setting it up
- **GitHub repo:** imrankhakwani-oss/fintiq-landing (Vercel auto-deploys)
- **Reddit account:** u/trader1311 — new, building karma, no links yet
- **LinkedIn:** Profile updated, featured added, 20 posts ready to go
- **Always check this document before suggesting something that might already be done**

---

## 14. IMPORTANT LINKS

| Resource | URL / Detail |
|----------|-------------|
| Landing site | https://fintiq.uk |
| App | https://app.fintiq.uk |
| GitHub | https://github.com/imrankhakwani-oss/fintiq-landing |
| Vercel deployment | fintiq-landing.vercel.app |
| Google Analytics | G-SFD342RVKK |
| Google Search Console | sc-domain:fintiq.uk |
| LinkedIn | linkedin.com/in/imran-khakwani-acsi-fca-41185710 |
| Reddit | u/trader1311 |
| Stripe | Integrated (individual £2.50, bundle £10) |
| Files location | C:\Users\imran\Desktop\Fintiq\Articles\ |

---

*To use this document: at the start of every new Claude session, paste this entire document and say "Read this — it's our project master document. Continue from where we left off."*
