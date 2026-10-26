/**
 * Fintiq — Cloudflare Worker: price proxy (locked to fintiq.uk)
 *
 * Changes from cloudflare-worker.js:
 *  1. CORS allows only Fintiq's own sites (was "*", i.e. any website).
 *  2. Requests without a Fintiq Origin/Referer are refused (403).
 *  3. Responses are cached at Cloudflare's edge for 6 hours, so repeat
 *     requests never reach Yahoo.
 *  4. Ticker format is validated.
 *
 * Also add a Cloudflare Rate Limiting rule on prices.fintiq.uk
 * (Security → WAF → Rate limiting rules), for example 60 requests per
 * minute per IP. That rule blocks scripts that fake the Origin header.
 */

const ALLOWED_ORIGINS = new Set([
  'https://fintiq.uk',
  'https://www.fintiq.uk',
  'https://app.fintiq.uk',
]);
const ALLOWED_PERIODS = new Set(['6mo', '1y', '2y', '3y', '5y']);
const TICKER_RE = /^[A-Z0-9.^=\-]{1,15}$/;
const CACHE_SECONDS = 6 * 3600;

function originOf(request) {
  const origin = request.headers.get('Origin');
  if (origin) return origin;
  const ref = request.headers.get('Referer');
  if (!ref) return null;
  try { return new URL(ref).origin; } catch { return null; }
}

function corsHeaders(origin) {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
    'Vary': 'Origin',
  };
}

function json(body, status, origin, extra = {}) {
  const headers = { 'Content-Type': 'application/json', 'X-Robots-Tag': 'noindex', ...extra };
  if (origin) Object.assign(headers, corsHeaders(origin));
  return new Response(JSON.stringify(body), { status, headers });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const parts = url.pathname.split('/').filter(Boolean);

    if (parts[0] === 'health') return json({ status: 'ok' }, 200, null);

    // Only Fintiq pages may call this proxy
    const origin = originOf(request);
    if (!origin || !ALLOWED_ORIGINS.has(origin)) {
      return json({ detail: 'Forbidden' }, 403, null);
    }

    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders(origin) });
    }
    if (request.method !== 'GET') return json({ detail: 'Method not allowed' }, 405, origin);

    if (parts[0] !== 'prices' || !parts[1]) {
      return json({ detail: 'Use /prices/{ticker}?period=1y' }, 400, origin);
    }

    const ticker = decodeURIComponent(parts[1]).toUpperCase().trim();
    if (!TICKER_RE.test(ticker)) return json({ detail: 'Invalid ticker' }, 400, origin);
    let period = url.searchParams.get('period') || '1y';
    if (!ALLOWED_PERIODS.has(period)) period = '1y';

    // Edge cache, keyed on ticker + period only
    const cache = caches.default;
    const cacheKey = new Request(`https://prices.fintiq.uk/cache/${encodeURIComponent(ticker)}/${period}`);
    const hit = await cache.match(cacheKey);
    if (hit) {
      const body = await hit.text();
      return new Response(body, { status: 200, headers: { 'Content-Type': 'application/json', 'X-Cache': 'HIT', ...corsHeaders(origin) } });
    }

    const yfUrl = `https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=${period}&interval=1d&includePrePost=false&events=history`;
    let yfResp;
    try {
      yfResp = await fetch(yfUrl, { headers: { 'User-Agent': 'Mozilla/5.0 (compatible; Fintiq/1.0)', 'Accept': 'application/json' } });
    } catch (e) {
      return json({ detail: 'Price service unavailable' }, 502, origin);
    }
    if (!yfResp.ok) {
      return json({ detail: `No price data for '${ticker}'` }, yfResp.status === 404 ? 404 : 502, origin);
    }

    const data = await yfResp.json();
    const result = data?.chart?.result?.[0];
    if (!result) return json({ detail: `No price history found for '${ticker}'` }, 404, origin);

    const ts = result.timestamp || [];
    const closes = result.indicators?.adjclose?.[0]?.adjclose || result.indicators?.quote?.[0]?.close || [];
    const prices = ts
      .map((t, i) => ({ date: new Date(t * 1000).toISOString().slice(0, 10), close: closes[i] != null ? Math.round(closes[i] * 10000) / 10000 : null }))
      .filter(p => p.close !== null && p.close > 0);
    if (!prices.length) return json({ detail: `No valid closing prices for '${ticker}'` }, 404, origin);

    const body = JSON.stringify({ ticker, count: prices.length, prices });
    ctx.waitUntil(cache.put(cacheKey, new Response(body, { headers: { 'Content-Type': 'application/json', 'Cache-Control': `public, max-age=${CACHE_SECONDS}` } })));
    return new Response(body, { status: 200, headers: { 'Content-Type': 'application/json', 'X-Cache': 'MISS', ...corsHeaders(origin) } });
  },
};
