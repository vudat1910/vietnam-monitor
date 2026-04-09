
const CM_CHART_CDN = 'https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js';

let _cmGoldChart = null;
let _cmFuelChart = null;
let _fuelSeries  = {};   
let _fuelTypes   = [];
let _activeFuel  = 'ron95';


function cmLoadScript(src) {
  return new Promise((res, rej) => {
    if (typeof LightweightCharts !== 'undefined') { res(); return; }
    if (document.querySelector(`script[src="${src}"]`)) {
      const check = setInterval(() => {
        if (typeof LightweightCharts !== 'undefined') { clearInterval(check); res(); }
      }, 100);
      return;
    }
    const s = document.createElement('script');
    s.src = src; s.onload = res; s.onerror = rej;
    document.head.appendChild(s);
  });
}

function cmFmt(n, dec = 0) {
  if (n == null || isNaN(n)) return '—';
  return n.toLocaleString('vi-VN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}
function cmSign(n) { return n > 0 ? '+' : ''; }
function cmUpDn(n) { return n > 0 ? '#16a34a' : n < 0 ? '#dc2626' : '#64748b'; }


function injectCommodityStyles() {
  if (document.getElementById('cm-styles')) return;
  const css = `
    #commodity-wrapper { padding: 0 10px 10px; }

    .cm-block {
      background: rgba(255,255,255,0.13);
      border: 1px solid rgba(255,255,255,0.36);
      border-radius: 16px;
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      box-shadow: 0 8px 32px rgba(17,24,39,0.10), inset 0 1px 0 rgba(255,255,255,0.55);
      padding: 16px;
      margin-bottom: 10px;
      position: relative;
      overflow: hidden;
    }
    .cm-block::before {
      content:'';
      position:absolute;inset:0;border-radius:16px;pointer-events:none;
      background:linear-gradient(180deg,rgba(255,255,255,0.18) 0%,rgba(255,255,255,0.04) 50%,transparent 100%);
    }

    /* Section header row */
    .cm-hdr {
      display: flex; align-items: center; justify-content: space-between;
      margin-bottom: 12px; flex-wrap: wrap; gap: 8px;
    }
    .cm-hdr-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .cm-sec-title {
      font-size: 13px; font-weight: 800; color: #0b1220;
      letter-spacing: .05em; text-transform: uppercase;
    }
    .cm-updated { font-size: 11px; color: #94a3b8; }

    /* Chart row: [Chart 70%] [Prediction 30%] */
    .cm-chart-row { display: grid; grid-template-columns: 70% 30%; gap: 14px; align-items: start; margin-top: 6px; }
    @media (max-width: 700px) { .cm-chart-row { grid-template-columns: 1fr; } }

    /* Mini prediction card (shared style) */
    .cm-pred-card {
      background: rgba(255,255,255,0.22);
      border: 1px solid rgba(255,255,255,0.4);
      border-radius: 12px; padding: 10px 12px; margin-top: 4px;
    }
    .cm-pred-label { font-size: 10px; font-weight: 700; letter-spacing:.07em; text-transform:uppercase; color:#64748b; margin-bottom:4px; }
    .cm-pred-value { font-size: 18px; font-weight: 800; color: #0b1220; }
    .cm-pred-chg   { font-size: 12px; font-weight: 600; margin: 1px 0; }
    .cm-pred-sub   { font-size: 10px; color: #94a3b8; margin-top: 2px; }
    .cm-pred-conf  {
      display: inline-block; font-size: 10px; font-weight: 600;
      border-radius: 999px; padding: 1px 7px; border: 1px solid; margin-top: 4px;
    }

    .cm-realtime-badge {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 10px; font-weight: 600; color: #16a34a;
      background: rgba(22,163,74,0.1); border-radius: 999px;
      padding: 2px 8px; border: 1px solid rgba(22,163,74,0.2);
    }
    .cm-realtime-dot {
      width: 6px; height: 6px; border-radius: 50%; background: #16a34a;
      animation: cmPulse 1.5s ease-in-out infinite;
    }
    @keyframes cmPulse { 0%,100%{opacity:1} 50%{opacity:.3} }
    @media (max-width: 700px) {
      .cm-split { grid-template-columns: 1fr; }
    }

    /* Type filter pills */
    .cm-pills { display: flex; gap: 6px; flex-wrap: wrap; }
    .cm-pill {
      padding: 4px 12px; border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.5);
      background: rgba(255,255,255,0.2);
      font-size: 11px; font-weight: 600; color: #475569;
      cursor: pointer; transition: all .18s; white-space: nowrap;
    }
    .cm-pill:hover { background: rgba(255,255,255,0.38); }
    .cm-pill.active { background: #0b1220; color: #fff; border-color: #0b1220; }

    /* Gold price cards grid — 4 equal columns full width */
    .cm-gold-cards {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 8px; margin-bottom: 12px;
    }
    @media (max-width: 900px) {
      .cm-gold-cards { grid-template-columns: repeat(2, 1fr); }
    }
    .cm-gold-card {
      background: rgba(255,255,255,0.22);
      border: 1px solid rgba(255,255,255,0.4);
      border-radius: 12px; padding: 10px 12px;
    }
    .cm-gold-card-name {
      font-size: 11px; font-weight: 700; color: #64748b;
      margin-bottom: 6px; text-transform: uppercase; letter-spacing: .04em;
    }
    .cm-gold-row { display: flex; justify-content: space-between; align-items: center; }
    .cm-gold-label { font-size: 11px; color: #94a3b8; }
    .cm-gold-val { font-size: 13px; font-weight: 700; color: #0b1220; }
    .cm-gold-sell { color: #dc2626 !important; }
    .cm-gold-buy  { color: #16a34a !important; }

    /* Chart containers */
    .cm-chart-wrap { width: 100%; height: 320px; border-radius: 10px; overflow: hidden; }
    .cm-chart-info {
      display: flex; gap: 14px; align-items: baseline;
      margin-bottom: 8px; flex-wrap: wrap;
    }
    .cm-chart-price { font-size: 20px; font-weight: 800; color: #0b1220; }
    .cm-chart-chg   { font-size: 13px; font-weight: 600; }
    .cm-chart-sub   { font-size: 11px; color: #94a3b8; }
    .cm-loading {
      height: 200px; display: flex; align-items: center;
      justify-content: center; color: #94a3b8; font-size: 12px;
    }

    /* Fuel current price strip */
    .cm-fuel-strip {
      display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px;
    }
    .cm-fuel-badge {
      background: rgba(255,255,255,0.22);
      border: 1px solid rgba(255,255,255,0.4);
      border-radius: 10px; padding: 8px 12px; flex: 1 1 130px;
      cursor: pointer; transition: all .18s;
    }
    .cm-fuel-badge:hover { background: rgba(255,255,255,0.36); }
    .cm-fuel-badge.active { border-color: rgba(59,130,246,.5); background: rgba(59,130,246,.08); }
    .cm-fuel-badge-name { font-size: 10px; font-weight: 700; color: #64748b; letter-spacing:.04em; }
    .cm-fuel-badge-price { font-size: 16px; font-weight: 800; color: #0b1220; margin-top: 2px; }
    .cm-fuel-badge-chg { font-size: 11px; font-weight: 600; }

    @media (max-width: 600px) {
      .cm-fuel-badge { flex: 1 1 100px; }
    }
  `;
  const el = document.createElement('style');
  el.id = 'cm-styles'; el.textContent = css;
  document.head.appendChild(el);
}


function ensureCommodityUI() {
  const wrap = document.getElementById('commodity-wrapper');
  if (!wrap || wrap.dataset.cmBuilt) return;
  wrap.dataset.cmBuilt = '1';

  wrap.innerHTML = `
    <!-- ── GOLD ── -->
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <div class="weather-title">GIÁ VÀNG</div>
      <span class="cm-realtime-badge"><span class="cm-realtime-dot"></span>Live</span>
      <span class="cm-updated" style="margin-left:auto;" id="cm-gold-updated"></span>
    </div>

    <div class="cm-block" id="cm-gold-block">
      <!-- Live SJC/DOJI price cards -->
      <div id="cm-gold-cards" class="cm-gold-cards">
        <div class="cm-loading" style="height:80px;grid-column:1/-1;">Đang lấy giá...</div>
      </div>

      <!-- Price info bar -->
      <div class="cm-chart-info" style="margin:4px 0;">
        <span class="cm-chart-price" id="cm-gold-intl-price">—</span>
        <span class="cm-chart-chg"  id="cm-gold-intl-chg">—</span>
        <span class="cm-chart-sub">Vàng quốc tế quy đổi VND/lượng</span>
      </div>

      <!-- Chart row -->
      <div class="cm-chart-row">
        <div class="cm-chart-wrap" id="cm-gold-chart">
          <div class="cm-loading">Đang tải biểu đồ...</div>
        </div>
        <div id="cm-gold-pred"></div>
      </div>
    </div>

    <!-- ── FUEL ── -->
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;margin-top:6px;">
      <div class="weather-title">GIÁ XĂNG DẦU</div>
      <span class="cm-realtime-badge"><span class="cm-realtime-dot"></span>Live</span>
      <span class="cm-updated" style="margin-left:auto;" id="cm-fuel-updated"></span>
    </div>

    <div class="cm-block" id="cm-fuel-block">
      <!-- Fuel type badge strip -->
      <div class="cm-fuel-strip" id="cm-fuel-strip">
        <div class="cm-loading" style="height:60px;width:100%;">Đang tải...</div>
      </div>

      <!-- Price info bar -->
      <div class="cm-chart-info" style="margin:4px 0;">
        <span class="cm-chart-price" id="cm-fuel-price">—</span>
        <span class="cm-chart-chg"  id="cm-fuel-chg">—</span>
        <span class="cm-chart-sub"  id="cm-fuel-sub">VND/lít</span>
      </div>

      <!-- Chart row -->
      <div class="cm-chart-row">
        <div>
          <div style="font-size:11px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px;" id="cm-fuel-chart-title">Lịch sử giá xăng dầu</div>
          <div class="cm-chart-wrap" id="cm-fuel-chart">
            <div class="cm-loading">Đang tải biểu đồ...</div>
          </div>
        </div>
        <div id="cm-fuel-pred"></div>
      </div>
    </div>
  `;
}


function makeAreaChart(containerId, data, lineColor, topColor) {
  const el = document.getElementById(containerId);
  if (!el || !data.length) return null;
  el.innerHTML = '';

  const chart = LightweightCharts.createChart(el, {
    width:  el.clientWidth || 600,
    height: 320,
    layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#475569' },
    grid: {
      vertLines: { color: 'rgba(148,163,184,0.12)' },
      horzLines: { color: 'rgba(148,163,184,0.12)' },
    },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: 'rgba(148,163,184,0.2)', scaleMargins: { top: 0.1, bottom: 0.1 } },
    timeScale: { borderColor: 'rgba(148,163,184,0.2)', timeVisible: false },
    handleScroll: true, handleScale: true,
  });

  const series = chart.addAreaSeries({
    lineColor, topColor, bottomColor: 'rgba(255,255,255,0)',
    lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
  });
  series.setData(data);
  chart.timeScale().fitContent();

  new ResizeObserver(() => {
    if (el) chart.applyOptions({ width: el.clientWidth || 600 });
  }).observe(el);

  return chart;
}

async function loadGoldCurrent() {
  try {
    const r = await fetch('http://localhost:5000/commodity/gold/current');
    const j = await r.json();
    const sources = j.sources || {};
    const updEl   = document.getElementById('cm-gold-updated');
    if (updEl && j.updatedAt) updEl.textContent = 'Cập nhật: ' + j.updatedAt;

    const container = document.getElementById('cm-gold-cards');
    if (!container) return;

    const allCards = [];
    for (const [srcName, items] of Object.entries(sources)) {
      items.forEach(it => allCards.push({ ...it, source: srcName }));
    }

    if (!allCards.length) {
      container.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px;">Không lấy được giá vàng. Kiểm tra kết nối internet hoặc trang SJC/DOJI đang bảo trì.</div>';
      return;
    }

    container.innerHTML = allCards.map(it => `
      <div class="cm-gold-card">
        <div class="cm-gold-card-name">
          <span style="background:rgba(0,0,0,0.08);border-radius:4px;padding:1px 5px;font-size:9px;margin-right:4px;">${it.source}</span>
          ${it.name}
        </div>
        <div class="cm-gold-row" style="margin-bottom:3px;">
          <span class="cm-gold-label">Mua vào</span>
          <span class="cm-gold-val cm-gold-buy">${cmFmt(it.buy / 1e6, 2)} tr</span>
        </div>
        <div class="cm-gold-row">
          <span class="cm-gold-label">Bán ra</span>
          <span class="cm-gold-val cm-gold-sell">${cmFmt(it.sell / 1e6, 2)} tr</span>
        </div>
      </div>
    `).join('');
  } catch (e) {
    console.warn('[Commodity] Gold current error:', e.message);
    const c = document.getElementById('cm-gold-cards');
    if (c) c.innerHTML = '<div style="color:#ef4444;font-size:12px;padding:8px;">Lỗi kết nối</div>';
  }
}

async function loadGoldHistory() {
  try {
    const r = await fetch('http://localhost:5000/commodity/gold/history');
    const j = await r.json();
    const data = j.data || [];
    if (!data.length) return;

    const last = data[data.length - 1];
    const prev = data.length > 1 ? data[data.length - 2] : null;
    const chg  = prev ? last.value - prev.value : 0;
    const pct  = prev ? chg / prev.value * 100 : 0;

    const priceEl = document.getElementById('cm-gold-intl-price');
    const chgEl   = document.getElementById('cm-gold-intl-chg');
    if (priceEl) priceEl.textContent = cmFmt(last.value / 1e6, 2) + ' tr/lượng';
    if (chgEl) {
      chgEl.style.color = cmUpDn(chg);
      chgEl.textContent = `${cmSign(chg)}${cmFmt(chg / 1000)} K (${cmSign(pct)}${cmFmt(pct, 2)}%)`;
    }

    _cmGoldChart = makeAreaChart('cm-gold-chart', data, '#f59e0b', 'rgba(245,158,11,0.22)');
    const updEl = document.getElementById('cm-gold-chart-updated');
    if (updEl) updEl.textContent = 'Cập nhật: ' + new Date().toLocaleTimeString('vi-VN');
  } catch (e) {
    console.warn('[Commodity] Gold history error:', e.message);
  }
}


async function loadFuel() {
  try {
    const [rHist, rCur] = await Promise.all([
      fetch('http://localhost:5000/commodity/fuel'),
      fetch('http://localhost:5000/commodity/fuel/current').catch(() => null),
    ]);
    const j    = await rHist.json();
    const jCur = rCur ? await rCur.json().catch(() => ({})) : {};
    const livePrices = jCur.prices || {};

    _fuelTypes  = j.types  || [];
    _fuelSeries = j.series || {};

    for (const ft of _fuelTypes) {
      const series = _fuelSeries[ft.key];
      if (!series) continue;
      for (const [label, price] of Object.entries(livePrices)) {
        const lbl = label.toLowerCase();
        const matches =
          (ft.key === 'ron95'    && lbl.includes('ron 95') && !lbl.includes('e10') && !lbl.includes('e5')) ||
          (ft.key === 'e10ron95' && lbl.includes('e10')) ||
          (ft.key === 'e5ron92'  && lbl.includes('e5')) ||
          (ft.key === 'do005'    && lbl.includes('0,05')) ||
          (ft.key === 'do0001'   && lbl.includes('0,001'));
        if (matches && price > 1000) {
          const today = new Date().toISOString().slice(0, 10);
          const last  = series.data[series.data.length - 1];
          if (!last || last.time !== today) {
            series.data.push({ time: today, value: price });
          } else {
            last.value = price;
          }
          break;
        }
      }
    }

    const strip = document.getElementById('cm-fuel-strip');
    if (strip) {
      strip.innerHTML = _fuelTypes.map(ft => {
        const d    = _fuelSeries[ft.key]?.data || [];
        const last = d[d.length - 1];
        const prev = d.length > 1 ? d[d.length - 2] : null;
        const chg  = prev ? last.value - prev.value : 0;
        const pct  = prev ? chg / prev.value * 100 : 0;
        return `
          <div class="cm-fuel-badge ${ft.key === _activeFuel ? 'active' : ''}"
               id="cm-fuel-badge-${ft.key}"
               onclick="cmSelectFuel('${ft.key}')">
            <div class="cm-fuel-badge-name">${ft.label}</div>
            <div class="cm-fuel-badge-price">${cmFmt(last?.value)} ₫</div>
            <div class="cm-fuel-badge-chg" style="color:${cmUpDn(chg)};">
              ${cmSign(chg)}${cmFmt(chg)} (${cmSign(pct)}${cmFmt(pct,2)}%)
            </div>
          </div>`;
      }).join('');
    }

    if (jCur.updatedAt) {
      const updEl = document.getElementById('cm-fuel-updated');
      if (updEl) updEl.textContent = 'Cập nhật: ' + jCur.updatedAt;
    }

    renderFuelChart(_activeFuel);
  } catch (e) {
    console.warn('[Commodity] Fuel error:', e.message);
    const c = document.getElementById('cm-fuel-chart');
    if (c) c.innerHTML = '<div class="cm-loading" style="color:#ef4444;">Lỗi tải dữ liệu xăng dầu</div>';
  }
}

function renderFuelChart(key) {
  _activeFuel = key;

  document.querySelectorAll('.cm-fuel-badge').forEach(b => b.classList.remove('active'));
  const active = document.getElementById(`cm-fuel-badge-${key}`);
  if (active) active.classList.add('active');

  const series = _fuelSeries[key];
  if (!series) return;
  const data = series.data || [];
  const ft   = _fuelTypes.find(t => t.key === key) || {};

  const last = data[data.length - 1];
  const prev = data.length > 1 ? data[data.length - 2] : null;
  const chg  = prev ? last.value - prev.value : 0;
  const pct  = prev ? chg / prev.value * 100 : 0;

  const priceEl = document.getElementById('cm-fuel-price');
  const chgEl   = document.getElementById('cm-fuel-chg');
  const subEl   = document.getElementById('cm-fuel-sub');
  if (priceEl) priceEl.textContent = cmFmt(last?.value) + ' ₫/lít';
  if (chgEl) {
    chgEl.style.color = cmUpDn(chg);
    chgEl.textContent = `${cmSign(chg)}${cmFmt(chg)} (${cmSign(pct)}${cmFmt(pct,2)}%) so với kỳ trước`;
  }
  if (subEl) subEl.textContent = `${ft.label || key} · VND/lít · Nguồn PVOIL`;

  const fuelChartUpdEl = document.getElementById('cm-fuel-chart-updated');
  if (fuelChartUpdEl) fuelChartUpdEl.textContent = 'Cập nhật: ' + new Date().toLocaleTimeString('vi-VN');

  const fuelTitleEl = document.getElementById('cm-fuel-chart-title');
  if (fuelTitleEl) fuelTitleEl.textContent = `Lịch sử giá ${ft.label || key}`;

  if (_cmFuelChart) { try { _cmFuelChart.remove(); } catch(e) {} _cmFuelChart = null; }
  const color = ft.color || '#3b82f6';
  const topC  = color.replace('rgb', 'rgba').replace(')', ', 0.20)');
  _cmFuelChart = makeAreaChart('cm-fuel-chart', data, color,
    color.startsWith('#') ? hexToRgba(color, 0.18) : topC);
}


function hexToRgba(hex, a) {
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${a})`;
}

window.cmSelectFuel = renderFuelChart;


async function initCommodity() {
  injectCommodityStyles();
  ensureCommodityUI();

  try {
    await cmLoadScript(CM_CHART_CDN);
    await Promise.all([
      loadGoldCurrent(),
      loadGoldHistory(),
      loadFuel(),
    ]);

    setInterval(loadGoldCurrent, 5 * 60 * 1000);

    setInterval(async () => {
      const updEl = document.getElementById('cm-gold-chart-updated');
      if (updEl) updEl.textContent = 'Đang cập nhật...';
      await loadGoldHistory();
    }, 15 * 60 * 1000);

    setInterval(async () => {
      const updEl = document.getElementById('cm-fuel-updated');
      if (updEl) updEl.textContent = 'Đang cập nhật...';
      await loadFuel();
    }, 30 * 60 * 1000);

  } catch (e) {
    console.error('[Commodity] Init error:', e);
  }

  loadGoldMLPrediction();
  loadFuelMLPrediction();
}

async function loadGoldMLPrediction() {
  let card = document.getElementById('cm-gold-pred');

  if (!card) {
    console.warn('[GoldML] cm-gold-pred chưa có, thử lại sau 500ms...');
    setTimeout(loadGoldMLPrediction, 500);
    return;
  }

  card.innerHTML = `<div style="padding:12px;font-size:11px;color:#94a3b8;">Đang tải dự đoán...</div>`;

  try {
    console.log('[GoldML] Gọi /ml/predict-gold...');
    const res = await fetch('http://localhost:5000/ml/predict-gold');
    console.log('[GoldML] Response status:', res.status);
    const j   = await res.json();
    console.log('[GoldML] Response data:', j);

    if (!j.ready) {
      card.innerHTML = `<div style="padding:12px;font-size:11px;color:#94a3b8;">${j.error || 'Model chưa sẵn sàng'}</div>`;
      if (j.error && j.error.includes('thử lại')) {
        setTimeout(loadGoldMLPrediction, 30000);
      }
      return;
    }

    const up    = j.direction_code === 1;
    const flat  = j.direction_code === 0;
    const color = up ? '#16a34a' : flat ? '#f59e0b' : '#dc2626';
    const arrow = up ? '▲' : flat ? '→' : '▼';
    const sign  = j.predicted_return >= 0 ? '+' : '';

    card.innerHTML = `
      <div class="mkt-pred-card">
        <div style="font-size:14px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#0b1220;margin-bottom:6px;">Dự Đoán Giá Vàng · XAU/USD</div>

        <div style="font-size:11px;color:#64748b;margin-bottom:4px;">$${j.gold_price_usd.toLocaleString()}/oz</div>

        <div style="display:flex;align-items:baseline;gap:8px;margin:6px 0;">
          <span style="font-size:26px;font-weight:900;color:${color};">${arrow}</span>
          <span style="font-size:20px;font-weight:800;color:${color};">${j.direction}</span>
        </div>

        <div style="font-size:22px;font-weight:700;color:#0b1220;">${sign}${j.predicted_return}%</div>
        <div style="font-size:11px;color:#64748b;margin:2px 0;">Trong ${j.horizon} phiên tới</div>

        <div style="margin:10px 0;padding:8px 10px;border-radius:10px;background:${color}14;border:1px solid ${color}33;">
          <div style="font-size:11px;color:#64748b;">Độ tin cậy</div>
          <div style="font-size:18px;font-weight:800;color:${color};">${j.confidence}%</div>
          <div style="background:rgba(0,0,0,0.06);border-radius:999px;height:4px;margin-top:4px;">
            <div style="width:${j.confidence}%;height:4px;border-radius:999px;background:${color};transition:width .6s;"></div>
          </div>
        </div>

        <div style="font-size:10px;color:#64748b;margin-bottom:6px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;">Features Importance</div>
        ${j.top_features.map(f => `
          <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:3px;">
            <span style="color:#475569;">${f.name}</span>
            <span style="font-weight:700;color:#334155;">${f.importance}%</span>
          </div>
        `).join('')}

        <div style="font-size:10px;color:#64748b;margin-top:8px;padding-top:8px;border-top:1px solid rgba(0,0,0,0.06);font-style:italic;font-weight:800;">
          ⚠ Lưu ý: Dự đoán này được tạo bởi AI, chỉ mang tính tham khảo và không phải tư vấn đầu tư.
        </div>
      </div>`;

  } catch (e) {
    console.error('[GoldML] Lỗi fetch:', e.name, e.message);
    card.innerHTML = `<div style="padding:12px;font-size:11px;color:#ef4444;">Lỗi: ${e.name} — ${e.message}</div>`;
  }
}

async function loadFuelMLPrediction() {
  let card = document.getElementById('cm-fuel-pred');
  if (!card) {
    setTimeout(loadFuelMLPrediction, 500);
    return;
  }

  card.innerHTML = `<div style="padding:12px;font-size:11px;color:#94a3b8;">Đang tải dự đoán...</div>`;

  try {
    const res = await fetch('http://localhost:5000/ml/predict-fuel');
    const j   = await res.json();

    if (!j.ready) {
      card.innerHTML = `<div style="padding:12px;font-size:11px;color:#94a3b8;">${j.error || 'Không lấy được dữ liệu'}</div>`;
      return;
    }

    const up    = j.direction_code === 1;
    const flat  = j.direction_code === 0;
    const color = up ? '#16a34a' : flat ? '#f59e0b' : '#dc2626';
    const arrow = up ? '▲' : flat ? '→' : '▼';
    const sign  = j.combined_impact >= 0 ? '+' : '';

    card.innerHTML = `
      <div class="mkt-pred-card">
        <div style="font-size:14px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#0b1220;margin-bottom:6px;">Dự Đoán Giá Xăng Dầu</div>

        <div style="font-size:11px;color:#64748b;margin-bottom:4px;">WTI $${j.wti_price}/thùng · Kỳ tới: ${j.next_adj_date}</div>

        <div style="display:flex;align-items:baseline;gap:8px;margin:6px 0;">
          <span style="font-size:26px;font-weight:900;color:${color};">${arrow}</span>
          <span style="font-size:20px;font-weight:800;color:${color};">${j.direction}</span>
        </div>

        <div style="font-size:22px;font-weight:700;color:#0b1220;">${sign}${j.est_change_pct}%</div>
        <div style="font-size:11px;color:#64748b;margin:2px 0;">Kỳ điều chỉnh tiếp theo</div>

        <div style="margin:10px 0;padding:8px 10px;border-radius:10px;background:${color}14;border:1px solid ${color}33;">
          <div style="font-size:11px;color:#64748b;">Độ tin cậy</div>
          <div style="font-size:18px;font-weight:800;color:${color};">${j.confidence}%</div>
          <div style="background:rgba(0,0,0,0.06);border-radius:999px;height:4px;margin-top:4px;">
            <div style="width:${j.confidence}%;height:4px;border-radius:999px;background:${color};transition:width .6s;"></div>
          </div>
        </div>

        <div style="font-size:10px;color:#64748b;margin-bottom:6px;font-weight:700;text-transform:uppercase;letter-spacing:.05em;">Các yếu tố tác động</div>
        ${j.factors.map(f => {
          const fColor = f.value > 0 ? '#16a34a' : f.value < 0 ? '#dc2626' : '#64748b';
          const fSign  = f.value > 0 ? '+' : '';
          return `
            <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:3px;">
              <span style="color:#475569;">${f.name}</span>
              <span style="font-weight:700;color:${fColor};">${fSign}${f.value.toFixed(2)}%</span>
            </div>`;
        }).join('')}

        <div style="font-size:10px;color:#64748b;margin-top:8px;padding-top:8px;border-top:1px solid rgba(0,0,0,0.06);font-style:italic;font-weight:800;">
          ⚠ Lưu ý: Dự đoán này được tạo bởi AI, chỉ mang tính chất tham khảo và không phải đầu tư tư vấn.
        </div>
      </div>`;

  } catch (e) {
    console.error('[FuelML] Lỗi fetch:', e.name, e.message);
    card.innerHTML = `<div style="padding:12px;font-size:11px;color:#ef4444;">Lỗi: ${e.name} — ${e.message}</div>`;
  }
}

document.addEventListener('DOMContentLoaded', initCommodity);
