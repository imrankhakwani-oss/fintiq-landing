/**
 * Fintiq Factor Widget — v1.0
 * ===========================
 * Embeds a single-stock factor analysis card anywhere in app.fintiq.uk.
 *
 * Usage (add to your fundamentals page):
 *
 *   <div id="fintiq-factor-widget" data-ticker="AAPL"></div>
 *   <script src="https://fintiq.uk/factor-widget.js"></script>
 *
 * The widget reads the [data-ticker] attribute and renders the factor card
 * for that stock automatically. If the ticker isn't in the screener universe,
 * it renders a "not covered" state gracefully.
 *
 * To update the ticker dynamically (e.g. when user changes stock):
 *   window.FintiqFactor.load('MSFT');
 */

(function () {
  'use strict';

  const DATA_URL  = 'https://fintiq.uk/screener-data.json';
  const META_URL  = 'https://fintiq.uk/screener-meta.json';
  const FULL_URL  = 'https://fintiq.uk/factor-screener.html';
  const SUB_URL   = 'https://buy.stripe.com/6oU00j0y61DUgUE6Z6aZi09';

  let cachedStocks = null;
  let cachedMeta   = null;

  // ── Styles ────────────────────────────────────────────────────────────────
  const CSS = `
  .fq-widget{font-family:'Inter',system-ui,sans-serif;background:linear-gradient(135deg,#0F2337,#162032);border:1px solid rgba(245,158,11,0.25);border-radius:12px;padding:20px 24px;color:#F1F5F9;font-size:14px;line-height:1.5}
  .fq-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;gap:12px}
  .fq-title{font-size:0.72rem;text-transform:uppercase;letter-spacing:0.08em;color:#64748B;font-weight:600}
  .fq-link{font-size:0.75rem;color:#F59E0B;text-decoration:none;font-weight:600}
  .fq-link:hover{text-decoration:underline}
  .fq-stock-row{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:16px}
  .fq-ticker{font-size:1.4rem;font-weight:900;color:#F1F5F9}
  .fq-name{font-size:0.8rem;color:#94A3B8;margin-top:2px}
  .fq-alpha-block{text-align:right;flex-shrink:0}
  .fq-alpha-val{font-size:1.6rem;font-weight:900}
  .fq-alpha-pos{color:#22c55e}
  .fq-alpha-neg{color:#ef4444}
  .fq-alpha-label{font-size:0.7rem;color:#475569;margin-top:2px}
  .fq-sig{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:20px;font-size:0.7rem;font-weight:700;margin-top:6px}
  .fq-sig-green{background:rgba(34,197,94,0.1);color:#22c55e;border:1px solid rgba(34,197,94,0.25)}
  .fq-sig-amber{background:rgba(245,158,11,0.1);color:#F59E0B;border:1px solid rgba(245,158,11,0.25)}
  .fq-sig-red{background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.2)}
  .fq-divider{border:none;border-top:1px solid rgba(255,255,255,0.06);margin:14px 0}
  .fq-bars{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}
  .fq-bar-row{display:flex;align-items:center;gap:8px}
  .fq-bar-lbl{font-size:0.65rem;color:#64748B;width:28px;text-align:right;font-weight:600;flex-shrink:0}
  .fq-bar-val{font-size:0.7rem;font-weight:700;width:38px;flex-shrink:0}
  .fq-track{flex:1;height:5px;background:rgba(255,255,255,0.06);border-radius:3px;position:relative;overflow:visible}
  .fq-fill{height:5px;border-radius:3px;position:absolute;top:0}
  .fq-center{position:absolute;left:50%;top:-2px;width:1px;height:9px;background:rgba(255,255,255,0.15)}
  .fq-insight{font-size:0.8rem;color:#94A3B8;line-height:1.6;font-style:italic;margin-bottom:14px}
  .fq-footer{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
  .fq-meta{font-size:0.68rem;color:#475569}
  .fq-cta{background:#F59E0B;color:#0A1628;padding:7px 16px;border-radius:6px;font-size:0.75rem;font-weight:700;text-decoration:none;white-space:nowrap}
  .fq-cta:hover{background:#FCD34D}
  .fq-loading{text-align:center;padding:28px 0;color:#64748B;font-size:0.85rem}
  .fq-spin{display:inline-block;width:18px;height:18px;border:2px solid rgba(245,158,11,0.2);border-top-color:#F59E0B;border-radius:50%;animation:fq-spin 0.8s linear infinite;vertical-align:middle;margin-right:8px}
  @keyframes fq-spin{to{transform:rotate(360deg)}}
  .fq-not-covered{text-align:center;padding:24px;color:#64748B;font-size:0.85rem}
  .fq-rank-badge{display:inline-block;background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.2);border-radius:6px;padding:2px 8px;font-size:0.68rem;font-weight:700;color:#F59E0B;margin-left:8px;vertical-align:middle}
  `;

  function injectStyles() {
    if (document.getElementById('fq-styles')) return;
    const style = document.createElement('style');
    style.id = 'fq-styles';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  // ── Data fetching ─────────────────────────────────────────────────────────
  async function fetchData() {
    if (cachedStocks) return { stocks: cachedStocks, meta: cachedMeta };
    const [dataRes, metaRes] = await Promise.all([
      fetch(DATA_URL + '?v=' + Date.now()),
      fetch(META_URL + '?v=' + Date.now()),
    ]);
    cachedStocks = (await dataRes.json()).stocks || [];
    cachedMeta   = await metaRes.json();
    return { stocks: cachedStocks, meta: cachedMeta };
  }

  // ── Factor bar HTML ───────────────────────────────────────────────────────
  const F_COLORS = { MKT:'#60a5fa', SMB:'#a78bfa', HML:'#f59e0b', MOM:'#34d399' };

  function barHTML(label, value, color) {
    const pct  = Math.min(Math.abs(value) / 1.6 * 50, 50);
    const left = value >= 0 ? 50 : (50 - pct);
    const sign = value >= 0 ? '+' : '';
    return `
      <div class="fq-bar-row">
        <span class="fq-bar-lbl">${label}</span>
        <div class="fq-track">
          <div class="fq-center"></div>
          <div class="fq-fill" style="left:${left}%;width:${pct}%;background:${color};${value < 0 ? 'opacity:0.6' : ''}"></div>
        </div>
        <span class="fq-bar-val" style="color:${value >= 0 ? color : '#64748B'}">${sign}${value.toFixed(2)}</span>
      </div>`;
  }

  // ── Render card ───────────────────────────────────────────────────────────
  function renderCard(container, stock, meta) {
    const a     = stock.alpha;
    const sign  = a >= 0 ? '+' : '';
    const aCls  = a >= 0 ? 'fq-alpha-pos' : 'fq-alpha-neg';
    const sigCls = { green:'fq-sig-green', amber:'fq-sig-amber', red:'fq-sig-red' }[stock.signal];
    const sigLbl = { green:'● Strong Alpha', amber:'◑ Marginal', red:'● Avoid' }[stock.signal];
    const rankBadge = stock.rank ? `<span class="fq-rank-badge">#${stock.rank} of ${meta.universe_count || '500+'}</span>` : '';

    container.innerHTML = `
      <div class="fq-widget">
        <div class="fq-header">
          <div class="fq-title">🔬 Factor Analysis · ${meta.lookback_years || 2}yr Lookback</div>
          <a href="${FULL_URL}" target="_blank" class="fq-link">Full Screener →</a>
        </div>

        <div class="fq-stock-row">
          <div>
            <div>
              <span class="fq-ticker">${stock.ticker}</span>${rankBadge}
            </div>
            <div class="fq-name">${stock.name}</div>
            <div class="fq-sig ${sigCls}" style="margin-top:8px">${sigLbl}</div>
          </div>
          <div class="fq-alpha-block">
            <div class="fq-alpha-val ${aCls}">${sign}${a.toFixed(1)}%</div>
            <div class="fq-alpha-label">alpha / year</div>
            <div style="font-size:0.68rem;color:#475569;margin-top:4px">p = ${stock.pval.toFixed(3)}</div>
          </div>
        </div>

        <hr class="fq-divider">

        <div class="fq-bars">
          ${barHTML('MKT', stock.beta - 1, F_COLORS.MKT)}
          ${barHTML('SMB', stock.smb, F_COLORS.SMB)}
          ${barHTML('HML', stock.hml, F_COLORS.HML)}
          ${barHTML('MOM', stock.mom, F_COLORS.MOM)}
        </div>

        <div class="fq-insight">${stock.insight}</div>

        <hr class="fq-divider">

        <div class="fq-footer">
          <div class="fq-meta">Updated ${meta.generated_date || 'weekly'} · Fama-French 4-Factor</div>
          <a href="${SUB_URL}" target="_blank" class="fq-cta">Unlock All 500+ →</a>
        </div>
      </div>`;
  }

  function renderNotCovered(container, ticker) {
    container.innerHTML = `
      <div class="fq-widget">
        <div class="fq-header">
          <div class="fq-title">🔬 Factor Analysis</div>
          <a href="${FULL_URL}" target="_blank" class="fq-link">Full Screener →</a>
        </div>
        <div class="fq-not-covered">
          <div style="font-size:1.5rem;margin-bottom:8px">📊</div>
          <div style="color:#94A3B8;margin-bottom:4px"><strong style="color:#F1F5F9">${ticker}</strong> is not in the current screener universe.</div>
          <div style="font-size:0.78rem">Coverage: S&amp;P 500 · NASDAQ 100 · Dow 30</div>
          <a href="${FULL_URL}" target="_blank" style="display:inline-block;margin-top:12px;color:#F59E0B;font-size:0.8rem;font-weight:600">Browse all covered stocks →</a>
        </div>
      </div>`;
  }

  function renderLoading(container) {
    container.innerHTML = `
      <div class="fq-widget">
        <div class="fq-loading">
          <span class="fq-spin"></span>Loading factor analysis...
        </div>
      </div>`;
  }

  // ── Public API ────────────────────────────────────────────────────────────
  async function load(ticker) {
    const container = document.getElementById('fintiq-factor-widget');
    if (!container) return;

    const t = (ticker || container.dataset.ticker || '').toUpperCase().trim();
    if (!t) return;

    injectStyles();
    renderLoading(container);

    try {
      const { stocks, meta } = await fetchData();
      const stock = stocks.find(s => s.ticker === t);
      if (stock) {
        renderCard(container, stock, meta);
      } else {
        renderNotCovered(container, t);
      }
    } catch (err) {
      container.innerHTML = `<div class="fq-widget"><div class="fq-not-covered" style="color:#ef4444">Factor data unavailable — <a href="${FULL_URL}" style="color:#F59E0B">view on Fintiq</a></div></div>`;
    }
  }

  // ── Auto-init ─────────────────────────────────────────────────────────────
  window.FintiqFactor = { load };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => load());
  } else {
    load();
  }

})();
