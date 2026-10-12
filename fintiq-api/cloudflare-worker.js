/**
 * Fintiq — Cloudflare Worker: Yahoo Finance Price Proxy
 *
 * Deploy this worker to replace api.fintiq.uk when you shut down Railway.
 *
 * HOW TO DEPLOY (one-time, ~5 minutes):
 * 1. Go to https://dash.cloudflare.com → Workers & Pages → Create Worker
 * 2. Paste this entire file into the editor, click Save & Deploy
 * 3. In the Worker settings → Triggers → Custom Domains, add: prices.fintiq.uk
 * 4. In pairs-trading.html, change:
 *      const PRICES_API = 'https://api.fintiq.uk';
 *    to:
 *      const PRICES_API = 'https://prices.fintiq.uk';
 *
 * Free tier: 100,000 requests/day — more than enough for fintiq.uk traffic.
 *
 * Supported route: GET /prices/{ticker}?period=1y
 * Allowed periods: 6mo, 1y, 2y, 3y, 5y
 */

const ALLOWED_PERIODS = new Set(['6mo', '1y', '2y', '3y', '5y']);

const CORS_HEADERS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

export default {
  async fetch(request) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS_HEADERS });
    }

    const url    = new URL(request.url);
    const parts  = url.pathname.split('/').filter(Boolean); // ['prices', 'AAPL']

    // Health check
    if (parts[0] === 'health') {
      return json({ status: 'ok' });
    }

    // Route: /prices/{ticker}
    if (parts[0] !== 'prices' || !parts[1]) {
      return json({ detail: 'Use /prices/{ticker}?period=1y' }, 400);
    }

    const ticker = parts[1].toUpperCase().trim();
    let   period = url.searchParams.get('period') || '1y';
    if (!ALLOWED_PERIODS.has(period)) period = '1y';

    // Fetch from Yahoo Finance chart API (server-side, no CORS issue)
    const yfUrl  = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=${period}&interval=1d&includePrePost=false&events=history`;

    let yfResp;
    try {
      yfResp = await fetch(yfUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (compatible; Fintiq/1.0)',
          'Accept':     'application/json',
        },
      });
    } catch (e) {
      return json({ detail: `Failed to reach Yahoo Finance: ${e.message}` }, 502);
    }

    if (!yfResp.ok) {
      return json({ detail: `Yahoo Finance returned ${yfResp.status} for '${ticker}'` }, yfResp.status === 404 ? 404 : 502);
    }

    const data   = await yfResp.json();
    const result = data?.chart?.result?.[0];

    if (!result) {
      const errMsg = data?.chart?.error?.description || `No price history found for '${ticker}'`;
      return json({ detail: errMsg }, 404);
    }

    const timestamps = result.timestamp || [];
    const closes     = result.indicators?.adjclose?.[0]?.adjclose
                    || result.indicators?.quote?.[0]?.close
                    || [];

    const prices = timestamps
      .map((ts, i) => ({
        date:  new Date(ts * 1000).toISOString().slice(0, 10),
        close: closes[i] != null ? Math.round(closes[i] * 10000) / 10000 : null,
      }))
      .filter(p => p.close !== null && p.close > 0);

    if (!prices.length) {
      return json({ detail: `No valid closing prices found for '${ticker}'` }, 404);
    }

    return json({ ticker, count: prices.length, prices });
  },
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS_HEADERS, 'Content-Type': 'application/json' },
  });
}
