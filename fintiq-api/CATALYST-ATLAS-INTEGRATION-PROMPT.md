I want to add a new free tool to Fintiq called **Catalyst Atlas**. The code is already written and tested on real Tesla data. Please integrate it, test it and help me deploy it. Read everything before changing anything.

## What it is

A free, plain-English tool for everyday retail investors. You type a ticker and it shows:
- **In a nutshell:** why the price moved this month, split into the whole market, the sector and interest rates, company news, and other buying and selling
- **Likely price range** for 1 week, 1 month and 3 months (7-in-10 and 9-in-10 ranges)
- **Coming up:** the next results date, how the shares reacted to past beats and misses, and a check on whether the price has already run up
- **What moves the company:** each type of news (earnings beat or miss, product news, politics, sales data, and so on), how often it moved the price, and an average path from day 0 to 3 months
- **The story so far:** rallies and falls at three time scales, each broken down by driver
- **Catalyst diary:** every news day found, with the move before, on the day, and 1 week, 1 month and 3 months after
- A button through to the paid **Stock Deep Dive** for that ticker (`/deep-dive.html?ticker=XXX`)

It is educational only: no buy or sell language, no entry or stop prices, no position sizes. The summary sentences come from templates, not AI, so the wording stays factual.

## Files (already in the Fintiq folder)

1. `Articles/catalyst-atlas.html` is the page. It matches the site's style: navy and amber, Inter, same nav, footer and GA tag. It calls `https://api.fintiq.uk/catalyst-atlas/{TICKER}`. With no `?ticker=` it shows a built-in Tesla example (as of 21 Oct 2026, labelled as a sample), so the page is never empty.
2. `Articles/fintiq-api/catalyst_atlas.py` is a standalone backend module. Main entry point: `build_atlas(ticker, kv_get, kv_set, tavily_search, anthropic_api_key)`.
   - Prices come from yfinance: the stock, SPY (or ^FTSE for .L tickers), an **equal-weight** sector ETF (RSPT, RSPD and so on, falling back to XLK/XLY if needed), and ^TNX.
   - It uses a rolling 250-day out-of-sample regression to split each day into market, sector/rates and company-specific parts.
   - Earnings beat or miss comes from `get_earnings_dates(limit=20)`. A reaction counts on the next session if results were after 12:00 New York time.
   - The biggest company-specific days (over 2.2 standard deviations, up to 14 of them) are labelled from news. It runs one Tavily search per day and then **one** Claude Haiku call (`claude-haiku-4-5-20251001`, temperature 0) that may only use the snippets, otherwise it returns "Unexplained". Labels are cached for 30 days in Upstash; the full result for 12 hours. So AI and Tavily cost is paid roughly once per ticker per month.
   - It also computes the footprints, scores (Laplace-smoothed counts), phases, quiet spells, and price ranges (options ATM implied vol if available, otherwise realised volatility).

## Tasks

### 1. Add the API route to `main.py`

Add near the other routes (and `from fastapi import HTTPException` if it isn't imported at module level):

```python
from catalyst_atlas import build_atlas as _build_atlas

@app.get("/catalyst-atlas/{ticker}")
def catalyst_atlas(ticker: str):
    """Free Catalyst Atlas tool. Cached 12h per ticker in Upstash; news labels cached 30 days."""
    from fastapi import HTTPException
    try:
        return _build_atlas(ticker, kv_get=_kv_get, kv_set=_kv_set,
                            tavily_search=_tavily_search,
                            anthropic_api_key=ANTHROPIC_API_KEY)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"[catalyst-atlas] {ticker}: {e}")
        raise HTTPException(status_code=502, detail="We couldn't build this analysis right now. Please try again shortly.")
```

- Make sure `catalyst_atlas.py` is deployed alongside `main.py` (check the Dockerfile `COPY` lines).
- Check that `requirements.txt` includes `numpy`, `pandas`, `yfinance` and `anthropic` (it already should).

### 2. Protect it

If the price-proxy guard from the earlier prompt (`guard_price_routes`) is in place, add `"/catalyst-atlas/"` to `_GUARDED_PREFIXES`, so only Fintiq pages can call it, with 60 requests per 10 minutes per IP. If the guard isn't in yet, do that first.

### 3. Test locally before deploying

- `python -c "from catalyst_atlas import build_atlas; import json; r=build_atlas('AAPL'); print(r['summary']); print(len(json.dumps(r)))"`. This should work without keys (no news labels: big days show as "Unexplained").
- Then with `TAVILY_API_KEY` and `ANTHROPIC_API_KEY` set, run TSLA and check that the big days get sensible labels (for example 29 Apr 2024 China self-driving, 6 Nov 2024 US election, 5 Jun 2025 Musk-Trump feud).
- Try a UK ticker (`SHEL.L`), a small cap, a ticker with little history, and a bad ticker (should return 400 with a friendly message).
- Time a cold request (no cache). If it's over about 45 seconds, tell me. We could pre-warm popular tickers with a daily job (see task 6).
- Check that the JSON response is roughly 50–80 KB.

### 4. Page checks

Open `catalyst-atlas.html` locally with the API URL pointed at localhost.
- Confirm a live ticker renders every section, the lens buttons and the "Show each time" lists work, and nothing scrolls sideways at phone width.
- Confirm `/catalyst-atlas.html?ticker=NVDA` loads NVDA directly, and the Deep Dive button opens `/deep-dive.html?ticker=NVDA`.

### 5. Add it to the site

- **tools.html:** add a card in the tools grid, plus a matching `ItemList` JSON-LD entry:
  ```html
  <div class="tool-card">
    <span class="tool-card-tag tag-free">NEW · FREE</span>
    <div class="tool-card-icon">🧭</div>
    <h3>Catalyst Atlas — Why Did This Share Move?</h3>
    <p>Type a ticker and see, in plain English, what has been driving the price, which news usually moves it, what happened 1 day to 3 months after past news, and a likely price range for the week, month and quarter.</p>
    <a class="tool-card-link" href="/catalyst-atlas.html">Open Catalyst Atlas →</a>
  </div>
  ```
  Match the exact structure of the existing cards if it differs.
- Add `https://www.fintiq.uk/catalyst-atlas.html` to `sitemap.xml`.
- Optionally, in `deep-dive.html`'s Catalyst section, add a small link: "See how {ticker} has reacted to past news → Catalyst Atlas".

### 6. Optional (tell me the cost before doing it)

A daily GitHub Action or Railway cron to pre-warm the 50 most-viewed tickers, so first visits are instant.

## Constraints

- Don't change Deep Dive, Stripe, bulletin or screener logic.
- Keep the page's disclaimer wording. It matches our FCA position (education only, not advice).
- Show me the full diff of `main.py`, `tools.html` and `sitemap.xml` before I deploy.
- **Separate security issue to raise with me:** `main.py` line ~26 has a real-looking FMP API key hard-coded as the default for `FMP_KEY`. It should come only from environment variables, and if the repo has ever been public, the key should be rotated.

## Known limitations (record these in CONTEXT.md)

- Data is still Yahoo (yfinance), the same as the rest of Fintiq. It must move to the licensed provider when we migrate.
- News labels are automatic and can be wrong. "Unexplained" is shown honestly when the news doesn't explain a move.
- Samples per company are small. The page marks anything under 4 examples as "Few examples".
- Next step: a forecast scorecard that logs each range and checks it later, to build a public track record.
