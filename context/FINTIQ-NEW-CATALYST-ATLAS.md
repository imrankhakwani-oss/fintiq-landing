# Fintiq-new: Catalyst Atlas project notes

Last updated: 10 November 2026. Upload this file to the "Fintiq-new" Claude Project as project knowledge.

## What Catalyst Atlas is
- Page: https://www.fintiq.uk/catalyst-atlas.html (Fintiq Ltd).
- What it does: you type a US or UK ticker and it explains why the share price moved. It splits each move into:
  - the whole stock market (SPY, or ^FTSE for UK shares);
  - the sector (equal-weight RSP* ETFs, or Brent oil BZ=F for Energy);
  - interest rates (^TNX, US shares only);
  - the company's own news.
- It then shows how the price reacted after each type of news, from day 0 to day 60, and the likely price ranges.
- The "Fintiq Analyst's view" gives a plain-English summary. Always use that exact name and never name a real bank.
- Audience: non-finance retail investors (the "housewife in Bristol" persona).
- Regulation: educational only and FCA-safe, so the page never gives buy, sell or hold advice.
- Display rules:
  - UK shares are shown in pounds, not pence.
  - There is no breadcrumb banner.
  - "Reading the numbers" and the full Analyst's view are expandable sections.
  - The first view shows the Analyst summary, the chart and the price range together.

## Files (on the computer at C:\Users\imran\Desktop\Fintiq\Articles)
- `fintiq-api\catalyst_atlas.py`: the engine (VERSION "v8").
  - News comes from Tavily searches, with Claude Haiku labelling each news day.
  - Claude Sonnet writes the Analyst's view.
  - Results are cached for 12 hours and news labels for 30 days, in Upstash.
- `fintiq-api\main.py` (deployed on Railway):
  - `/catalyst-atlas/{ticker}`: the main lookup. Only requests from the Fintiq site are accepted, with a limit of 30 lookups per 10 minutes per IP.
  - `/atlas/account`: shows a signed-in user's searches.
  - `/atlas/checkout`: starts a Stripe payment.
  - `/stripe/webhook`: Stripe's payment confirmation.
  - The Tesla auto-refresh thread.
- `catalyst-atlas.html`: the page, deployed on Vercel.
- Also changed:
  - `deep-dive.html` has an "Open Catalyst Atlas" button in its catalyst section.
  - `tools.html` has the card "NEW · TRY FREE".
  - `index.html` and `sitemap.xml` link to the page.

## Paywall (decided November 2026)
- Tesla is the only free company and needs no sign-in. It refreshes itself automatically in the background about every 10 hours. Fintiq bears that cost, roughly £2–3 a month.
- Every other company needs:
  - a sign-in with an emailed 6-digit code;
  - a credit pack: **10 searches for £2.29 / US $2.99**.
- How the pack works:
  - It is a one-off payment, not a subscription, and searches never expire.
  - Reopening the same company within 24 hours is free.
- New accounts get **no free search**. Setting the Railway variable `ATLAS_FREE_SEARCHES=1` would turn one back on.
- Pack settings are Railway variables: `ATLAS_PACK_CREDITS` (10), `ATLAS_PACK_PENCE` (229), `ATLAS_PACK_CENTS` (299).
- Stripe:
  - The price is set in the code, so no Stripe product is needed.
  - The existing webhook (`https://api.fintiq.uk/stripe/webhook`) already listens to `checkout.session.completed`.
  - Pack payments carry the metadata `product=atlas_credits`, so they never switch on a Deep Dive subscription.
- Database (SQLite on Railway, in `/data/auth.db`) has three tables:
  - `atlas_credits`: searches left per account.
  - `atlas_unlocks`: 24-hour reopen access.
  - `atlas_payments`: makes sure each payment adds searches only once.
- Costs:
  - A new company costs about 20–25p (Tavily about $0.24, plus Haiku and Sonnet).
  - A company already cached costs about 2p.
  - Stripe takes about 1.5% + 20p per pack.

## Deploy commands (push the backend before the website)
```
cd C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api
git add main.py
git commit -m "..."
git push origin master:main
```
```
cd C:\Users\imran\Desktop\Fintiq\Articles
git add catalyst-atlas.html
git commit -m "..."
git push origin master:main
```
- Name each file in `git add`. Never use `git add .`, because the GitHub repo is public.
- `.vercelignore` keeps `fintiq-api/`, `context/`, `*.md`, `*.py` and `*.bat` off the website.

## Open items
1. Done (deployed by 10 November 2026): the "no free search + Tesla auto-refresh" change is live in main.py and catalyst-atlas.html.
2. Next step: make a £2.29 test purchase:
   - The page should show 10 searches.
   - In Stripe, go to Developers → Webhooks → Event deliveries. The payment should show status 200. A 400 means `STRIPE_WEBHOOK_SECRET` in Railway doesn't match the signing secret in Stripe.
   - Refund the payment afterwards.
3. Deferred:
   - Bundle Catalyst Atlas with the Deep Dive subscription at £5/month.
   - Cut API costs (fewer Tavily searches).
4. Security advice still open:
   - Rotate the hard-coded FMP key, move it to a Railway variable, and consider making the GitHub repo private.
   - Lock down the price proxy (see PRICE-PROXY-FIX-PROMPT.md).
5. Long term: move from Yahoo and other free data to a licensed provider such as FMP once there is traction (about 1,000 subscribers).
