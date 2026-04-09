const CHART_CDN = 'https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js';

const INDEX_CFG = {
  VNINDEX: { label: 'VNINDEX', color: '#3b82f6', url: 'https://www.tradingview.com/symbols/HOSE-VNINDEX/' },
  VN30:    { label: 'VN30',    color: '#8b5cf6', url: 'https://www.tradingview.com/symbols/HOSE-VN30/' },
  HNX:     { label: 'HNX',     color: '#10b981', url: 'https://www.tradingview.com/symbols/HNX-HNXINDEX/' },
  UPCOM:   { label: 'UPCOM',   color: '#f59e0b', url: 'https://www.tradingview.com/symbols/UPCOM-UPCOM/' },
};

const STOCK_LIST = [
  { sym: 'VNM',  name: 'Vinamilk' },
  { sym: 'FPT',  name: 'FPT Corporation' },
  { sym: 'VIC',  name: 'Vingroup' },
  { sym: 'VHM',  name: 'Vinhomes' },
  { sym: 'HPG',  name: 'Hòa Phát Group' },
  { sym: 'MWG',  name: 'Mobile World' },
  { sym: 'VCB',  name: 'Vietcombank' },
  { sym: 'TCB',  name: 'Techcombank' },
  { sym: 'BID',  name: 'BIDV' },
  { sym: 'SSI',  name: 'SSI Securities' },
  { sym: 'MSN',  name: 'Masan Group' },
  { sym: 'GAS',  name: 'PetroVietnam Gas' },
  { sym: 'ACB',  name: 'ACB Bank' },
  { sym: 'HDB',  name: 'HDBank' },
  { sym: 'MBB',  name: 'MB Bank' },
  { sym: 'PNJ',  name: 'PNJ Jewelry' },
  { sym: 'CTG',  name: 'Vietinbank' },
  { sym: 'VPB',  name: 'VPBank' },
  { sym: 'TPB',  name: 'TPBank' },
  { sym: 'PLX',  name: 'Petrolimex' },
  { sym: 'POW',  name: 'PV Power' },
  { sym: 'REE',  name: 'REE Corporation' },
  { sym: 'DXG',  name: 'Đất Xanh Group' },
  { sym: 'KDH',  name: 'Khang Điền' },
  { sym: 'NVL',  name: 'Novaland' },
  { sym: 'PDR',  name: 'Phát Đạt Real Estate' },
  { sym: 'VRE',  name: 'Vincom Retail' },
  { sym: 'SAB',  name: 'Sabeco' },
  { sym: 'DHG',  name: 'Dược Hậu Giang' },
  { sym: 'DGC',  name: 'Đức Giang Chemicals' },
  { sym: 'GMD',  name: 'Gemadept' },
  { sym: 'HAG',  name: 'Hoàng Anh Gia Lai' },
  { sym: 'HBC',  name: 'Hòa Bình Construction' },
  { sym: 'IDC',  name: 'IDICO' },
  { sym: 'IMP',  name: 'Imexpharm' },
  { sym: 'KBC',  name: 'Kinh Bắc City' },
  { sym: 'LGC',  name: 'Long Giang' },
  { sym: 'MCH',  name: 'Masan Consumer' },
  { sym: 'NAB',  name: 'Nam A Bank' },
  { sym: 'OCB',  name: 'Orient Commercial Bank' },
  { sym: 'SHB',  name: 'SHBank' },
  { sym: 'STB',  name: 'Sacombank' },
  { sym: 'VIB',  name: 'VIB Bank' },
  { sym: 'VND',  name: 'VNDirect Securities' },
  { sym: 'HCM',  name: 'HSC Securities' },
  { sym: 'CII',  name: 'CII Infrastructure' },
  { sym: 'EIB',  name: 'Eximbank' },
  { sym: 'LPB',  name: 'LienVietPostBank' },
  { sym: 'PVS',  name: 'PetroVietnam Services' },
  { sym: 'VCI',  name: 'Viet Capital Securities' },
];

let _stockChart   = null;
let _volSeries    = null;
let _currentSym   = 'VNM';
let _currentRange = '3M';


function loadScript(src) {
  return new Promise((res, rej) => {
    if (document.querySelector(`script[src="${src}"]`)) { res(); return; }
    const s = document.createElement('script');
    s.src = src; s.onload = res; s.onerror = rej;
    document.head.appendChild(s);
  });
}

function fmtNum(n, dec = 2) {
  if (n == null || isNaN(n)) return '—';
  return n.toLocaleString('vi-VN', { minimumFractionDigits: dec, maximumFractionDigits: dec });
}

function fmtVol(v) {
  if (!v) return '—';
  if (v >= 1e6) return (v / 1e6).toFixed(2) + ' tr';
  if (v >= 1e3) return (v / 1e3).toFixed(1) + ' k';
  return v.toString();
}

function sign(n) { return n > 0 ? '+' : ''; }
function colorClass(n) { return n > 0 ? 'mkt-up' : n < 0 ? 'mkt-dn' : 'mkt-flat'; }


function injectMktStyles() {
  if (document.getElementById('mkt-styles')) return;
  const css = `
    /* ── Index header strip ── */
    .mkt-idx-strip {
      display: flex;
      gap: 12px;
      margin-bottom: 16px;
      flex-wrap: wrap;
    }
    .mkt-idx-card {
      flex: 1 1 160px;
      background: rgba(255,255,255,0.18);
      border: 1px solid rgba(255,255,255,0.35);
      border-radius: 14px;
      backdrop-filter: blur(12px);
      padding: 12px 16px;
      cursor: pointer;
      text-decoration: none;
      transition: background .2s, transform .15s;
    }
    .mkt-idx-card:hover { background: rgba(255,255,255,0.28); transform: translateY(-2px); }
    .mkt-idx-label {
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .08em;
      opacity: .7;
      color: #1e293b;
      text-transform: uppercase;
    }
    .mkt-idx-price {
      font-size: 22px;
      font-weight: 700;
      color: #1e293b;
      line-height: 1.2;
      margin: 4px 0 2px;
    }
    .mkt-idx-change {
      font-size: 12px;
      font-weight: 600;
    }
    .mkt-idx-time {
      font-size: 11px;
      color: #64748b;
      margin-left: auto;
      align-self: center;
      white-space: nowrap;
    }
    .mkt-up   { color: #16a34a; }
    .mkt-dn   { color: #dc2626; }
    .mkt-flat { color: #64748b; }

    /* ── Stock section ── */
    .mkt-stock-section {
      background: rgba(255,255,255,0.18);
      border: 1px solid rgba(255,255,255,0.35);
      border-radius: 16px;
      backdrop-filter: blur(12px);
      padding: 16px;
    }
    /* Chart row: chart 70% | prediction 30% */
    .mkt-chart-row {
      display: grid;
      grid-template-columns: 1fr 30%;
      gap: 14px;
      align-items: start;
      margin-top: 10px;
    }
    @media (max-width: 700px) { .mkt-chart-row { grid-template-columns: 1fr; } }
    .mkt-stock-title {
      font-size: 13px;
      font-weight: 700;
      color: #1e293b;
      letter-spacing: .04em;
    }
    /* ── Mini prediction card ── */
    .mkt-pred-card {
      background: rgba(255,255,255,0.22);
      border: 1px solid rgba(255,255,255,0.4);
      border-radius: 12px;
      padding: 10px 12px;
      margin-top: 4px;
    }
    .mkt-pred-label {
      font-size: 10px; font-weight: 700; letter-spacing: .07em;
      text-transform: uppercase; color: #64748b; margin-bottom: 4px;
    }
    .mkt-pred-value { font-size: 18px; font-weight: 800; color: #0b1220; }
    .mkt-pred-chg   { font-size: 12px; font-weight: 600; margin: 1px 0; }
    .mkt-pred-horizon { font-size: 10px; color: #94a3b8; margin-top: 2px; }
    .mkt-pred-conf {
      display: inline-block; font-size: 10px; font-weight: 600;
      border-radius: 999px; padding: 1px 7px; border: 1px solid;
      margin-top: 4px;
    }
    .mkt-realtime-badge {
      display: inline-flex; align-items: center; gap: 4px;
      font-size: 10px; font-weight: 600; color: #16a34a;
      background: rgba(22,163,74,0.1); border-radius: 999px;
      padding: 2px 8px; border: 1px solid rgba(22,163,74,0.2);
    }
    .mkt-realtime-dot {
      width: 6px; height: 6px; border-radius: 50%;
      background: #16a34a;
      animation: mktPulse 1.5s ease-in-out infinite;
    }
    @keyframes mktPulse {
      0%,100% { opacity: 1; } 50% { opacity: 0.3; }
    }

    /* ── Search input ── */
    .mkt-search-wrap {
      position: relative;
      flex: 1 1 200px;
      max-width: 280px;
    }
    .mkt-search-input {
      width: 100%;
      padding: 8px 36px 8px 12px;
      border-radius: 10px;
      border: 1px solid rgba(255,255,255,0.5);
      background: rgba(255,255,255,0.25);
      backdrop-filter: blur(8px);
      font-size: 13px;
      font-weight: 600;
      color: #1e293b;
      outline: none;
      box-sizing: border-box;
      text-transform: uppercase;
      letter-spacing: .05em;
      transition: border .2s, background .2s;
    }
    .mkt-search-input::placeholder { text-transform: none; letter-spacing: 0; color: #94a3b8; font-weight: 400; }
    .mkt-search-input:focus {
      border-color: rgba(59,130,246,0.6);
      background: rgba(255,255,255,0.4);
    }
    .mkt-search-btn {
      position: absolute;
      right: 6px; top: 50%;
      transform: translateY(-50%);
      background: #3b82f6;
      border: none;
      border-radius: 7px;
      padding: 4px 8px;
      color: #fff;
      font-size: 11px;
      font-weight: 700;
      cursor: pointer;
      letter-spacing: .04em;
    }
    .mkt-search-btn:hover { background: #2563eb; }
    .mkt-dropdown {
      position: absolute;
      top: calc(100% + 4px);
      left: 0; right: 0;
      background: rgba(255,255,255,0.92);
      backdrop-filter: blur(16px);
      border: 1px solid rgba(0,0,0,.08);
      border-radius: 10px;
      box-shadow: 0 8px 24px rgba(0,0,0,.12);
      z-index: 999;
      max-height: 200px;
      overflow-y: auto;
      display: none;
    }
    .mkt-dropdown.open { display: block; }
    .mkt-dd-item {
      padding: 8px 12px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
      transition: background .15s;
    }
    .mkt-dd-item:hover { background: rgba(59,130,246,.08); }
    .mkt-dd-sym {
      font-weight: 700;
      color: #1e293b;
      min-width: 42px;
    }
    .mkt-dd-name { color: #64748b; font-size: 12px; }

    /* ── Range buttons ── */
    .mkt-ranges {
      display: flex;
      gap: 6px;
    }
    .mkt-range {
      padding: 5px 12px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.5);
      background: rgba(255,255,255,0.2);
      font-size: 12px;
      font-weight: 600;
      color: #475569;
      cursor: pointer;
      transition: all .2s;
    }
    .mkt-range:hover { background: rgba(255,255,255,0.4); }
    .mkt-range.active {
      background: #3b82f6;
      color: #fff;
      border-color: #3b82f6;
    }

    /* ── Stock info bar ── */
    .mkt-stock-info {
      display: flex;
      align-items: baseline;
      gap: 12px;
      margin-bottom: 10px;
      flex-wrap: wrap;
    }
    .mkt-info-sym {
      font-size: 18px;
      font-weight: 800;
      color: #1e293b;
    }
    .mkt-info-price {
      font-size: 20px;
      font-weight: 700;
      color: #1e293b;
    }
    .mkt-info-change {
      font-size: 14px;
      font-weight: 600;
    }
    .mkt-info-meta {
      font-size: 12px;
      color: #64748b;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .mkt-info-meta span { display: flex; gap: 4px; }
    .mkt-info-meta b { color: #334155; }

    /* ── Chart ── */
    #mkt-stock-chart {
      width: 100%;
      height: 320px;
      border-radius: 10px;
      overflow: hidden;
    }
    #mkt-chart-loading {
      text-align: center;
      padding: 40px 0;
      color: #94a3b8;
      font-size: 13px;
    }
    @media (max-width: 700px) {
      .mkt-stock-section { grid-template-columns: 1fr; }
      .mkt-idx-card { flex: 1 1 130px; }
      .mkt-idx-price { font-size: 18px; }
    }
  `;
  const el = document.createElement('style');
  el.id = 'mkt-styles';
  el.textContent = css;
  document.head.appendChild(el);
}


function ensureMarketUI() {
  const wrap = document.getElementById('market-wrapper');
  if (!wrap || wrap.dataset.mktBuilt) return;
  wrap.dataset.mktBuilt = '1';

  wrap.innerHTML = `
    <!-- Title pill (same style as weather-title) -->
    <div class="weather-header-row" style="margin-bottom:10px;">
      <div class="weather-title">THỊ TRƯỜNG CHỨNG KHOÁN</div>
      <div style="font-size:11px;color:#64748b;" id="mkt-update-time"></div>
    </div>

    <div class="mkt-idx-strip" id="mkt-idx-strip">
      ${Object.entries(INDEX_CFG).map(([key, cfg]) => `
        <a class="mkt-idx-card" href="${cfg.url}" target="_blank" id="mkt-card-${key}">
          <div class="mkt-idx-label" style="color:${cfg.color}">${cfg.label}</div>
          <div class="mkt-idx-price" id="mkt-price-${key}">—</div>
          <div class="mkt-idx-change" id="mkt-chg-${key}">—</div>
        </a>
      `).join('')}
    </div>

    <!-- Stock chart section -->
    <div class="mkt-stock-section">

      <!-- Controls -->
      <div style="margin-bottom:12px;">
        <!-- Title row -->
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
          <div class="mkt-stock-title">BIỂU ĐỒ CỔ PHIẾU</div>
          <span class="mkt-realtime-badge"><span class="mkt-realtime-dot"></span>Live</span>
        </div>
        <!-- Search + range on same row -->
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <div class="mkt-search-wrap" style="flex:1 1 180px;">
            <input id="mkt-sym-input" class="mkt-search-input" type="text"
              placeholder="Tìm mã (VNM, FPT...)" autocomplete="off"
              oninput="mktOnInput(this.value)" onkeydown="mktOnKey(event)" />
            <button class="mkt-search-btn" onclick="mktSearch()">XEM</button>
            <div class="mkt-dropdown" id="mkt-dropdown"></div>
          </div>
          <div class="mkt-ranges">
            ${['1M','3M','1Y','2Y'].map(r =>
              `<button class="mkt-range${r==='3M'?' active':''}" onclick="mktSetRange('${r}')">${r}</button>`
            ).join('')}
          </div>
        </div>
      </div>

      <div class="mkt-stock-info" id="mkt-stock-info">
        <span class="mkt-info-sym" id="mkt-info-sym">VNM</span>
        <span class="mkt-info-price" id="mkt-info-price">—</span>
        <span class="mkt-info-change" id="mkt-info-chg">—</span>
        <div class="mkt-info-meta">
          <span>H: <b id="mkt-info-h">—</b></span>
          <span>L: <b id="mkt-info-l">—</b></span>
          <span>KL: <b id="mkt-info-vol">—</b></span>
        </div>
      </div>

      <!-- Chart row: [Chart 70%] [Prediction 30%] -->
      <div class="mkt-chart-row">
        <div>
          <div id="mkt-chart-loading" style="display:none;padding:40px 0;text-align:center;color:#94a3b8;">Đang tải...</div>
          <div id="mkt-stock-chart"></div>
        </div>
        <div id="mkt-pred-card"></div>
      </div>
    </div>
  `;
}


function mktOnInput(val) {
  const dd = document.getElementById('mkt-dropdown');
  if (!dd) return;
  const q = val.trim().toUpperCase();
  if (!q) { dd.classList.remove('open'); return; }

  const matches = STOCK_LIST.filter(s =>
    s.sym.startsWith(q) || s.name.toUpperCase().includes(q)
  ).slice(0, 8);

  if (!matches.length) { dd.classList.remove('open'); return; }

  dd.innerHTML = matches.map(s => `
    <div class="mkt-dd-item" onclick="mktPickStock('${s.sym}')">
      <span class="mkt-dd-sym">${s.sym}</span>
      <span class="mkt-dd-name">${s.name}</span>
    </div>
  `).join('');
  dd.classList.add('open');
}

function mktOnKey(e) {
  if (e.key === 'Enter') {
    const dd = document.getElementById('mkt-dropdown');
    if (dd) dd.classList.remove('open');
    mktSearch();
  }
  if (e.key === 'Escape') {
    const dd = document.getElementById('mkt-dropdown');
    if (dd) dd.classList.remove('open');
  }
}

function mktSearch() {
  const inp = document.getElementById('mkt-sym-input');
  const sym = inp ? inp.value.trim().toUpperCase() : '';
  if (!sym) return;
  mktPickStock(sym);
}

function mktPickStock(sym) {
  const dd = document.getElementById('mkt-dropdown');
  if (dd) dd.classList.remove('open');
  const inp = document.getElementById('mkt-sym-input');
  if (inp) inp.value = sym;
  _currentSym = sym;
  loadStockChart(sym, _currentRange);
}

document.addEventListener('click', e => {
  if (!e.target.closest('.mkt-search-wrap')) {
    const dd = document.getElementById('mkt-dropdown');
    if (dd) dd.classList.remove('open');
  }
});


async function refreshIndexPrices() {
  try {
    const r = await fetch('http://localhost:5000/market');
    const j = await r.json();
    const indices = j.indices || {};
    const now = new Date();
    const timeStr = now.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const el = document.getElementById('mkt-update-time');
    if (el) el.textContent = 'Cập nhật: ' + timeStr;

    for (const [key] of Object.entries(INDEX_CFG)) {
      const d = indices[key];
      if (!d) continue;
      const priceEl = document.getElementById(`mkt-price-${key}`);
      const chgEl   = document.getElementById(`mkt-chg-${key}`);
      if (priceEl) priceEl.textContent = fmtNum(d.price, 2);
      if (chgEl) {
        const cls = colorClass(d.change_pct);
        chgEl.className = `mkt-idx-change ${cls}`;
        chgEl.textContent = `${sign(d.change)}${fmtNum(d.change, 2)} (${sign(d.change_pct)}${fmtNum(d.change_pct, 2)}%)`;
      }
    }
  } catch (e) {
    console.warn('[Market] Index fetch error:', e.message);
  }
}


async function loadStockChart(symbol, range) {
  _currentSym   = symbol;
  _currentRange = range;

  document.querySelectorAll('.mkt-range').forEach(b => {
    b.classList.toggle('active', b.textContent === range);
  });

  const loading = document.getElementById('mkt-chart-loading');
  const chartEl = document.getElementById('mkt-stock-chart');
  if (loading) loading.style.display = 'block';
  if (chartEl) chartEl.innerHTML = '';

  if (_stockChart) {
    try { _stockChart.remove(); } catch(e) {}
    _stockChart = null;
    _volSeries  = null;
  }

  try {
    const res  = await fetch(`http://localhost:5000/stock/history?symbol=${symbol}&range=${range}`);
    const json = await res.json();
    const data = json.data || [];

    if (loading) loading.style.display = 'none';

    if (!data.length) {
      if (chartEl) chartEl.innerHTML = `<div style="padding:60px;text-align:center;color:#94a3b8;font-size:13px;">Không tìm thấy dữ liệu cho mã <b>${symbol}</b></div>`;
      updateStockInfoEmpty(symbol);
      return;
    }

    data.sort((a, b) => a.time.localeCompare(b.time));

    const last = data[data.length - 1];
    const prev = data.length > 1 ? data[data.length - 2] : null;
    updateStockInfo(symbol, last, prev);
    loadMLPrediction(symbol);

    if (!chartEl) return;
    const w = chartEl.clientWidth || chartEl.offsetWidth || 800;
    const h = 320;

    _stockChart = LightweightCharts.createChart(chartEl, {
      width: w,
      height: h,
      layout: {
        background: { type: 'solid', color: 'transparent' },
        textColor: '#475569',
      },
      grid: {
        vertLines: { color: 'rgba(148,163,184,0.15)' },
        horzLines: { color: 'rgba(148,163,184,0.15)' },
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: 'rgba(148,163,184,0.3)', scaleMargins: { top: 0.08, bottom: 0.28 } },
      timeScale: { borderColor: 'rgba(148,163,184,0.3)', timeVisible: true },
      handleScroll: true,
      handleScale: true,
    });

    const candleSeries = _stockChart.addCandlestickSeries({
      upColor:      '#16a34a',
      downColor:    '#dc2626',
      borderUpColor:   '#16a34a',
      borderDownColor: '#dc2626',
      wickUpColor:     '#16a34a',
      wickDownColor:   '#dc2626',
    });
    candleSeries.setData(data.map(d => ({
      time:  d.time,
      open:  d.open,
      high:  d.high,
      low:   d.low,
      close: d.close,
    })));

    _volSeries = _stockChart.addHistogramSeries({
      color:     '#93c5fd',
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
    });
    _stockChart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.75, bottom: 0 } });
    _volSeries.setData(data.map(d => ({
      time:  d.time,
      value: d.volume,
      color: d.close >= d.open ? 'rgba(22,163,74,0.4)' : 'rgba(220,38,38,0.4)',
    })));

    _stockChart.timeScale().fitContent();

    const ro = new ResizeObserver(() => {
      if (_stockChart && chartEl) {
        _stockChart.applyOptions({ width: chartEl.clientWidth || 800 });
      }
    });
    ro.observe(chartEl);

    _stockChart.subscribeCrosshairMove(param => {
      if (!param || !param.time) {
        updateStockInfo(symbol, last, prev);
        return;
      }
      const bar = param.seriesData ? param.seriesData.get(candleSeries) : null;
      if (bar) {
        const idx = data.findIndex(d => d.time === param.time || d.time === String(param.time));
        const prevBar = idx > 0 ? data[idx - 1] : null;
        updateStockInfo(symbol, { ...bar, volume: data[idx]?.volume }, prevBar ? { close: prevBar.close } : null);
      }
    });

  } catch (err) {
    if (loading) loading.style.display = 'none';
    console.error('[Market] Stock chart error:', err);
    if (chartEl) chartEl.innerHTML = `<div style="padding:60px;text-align:center;color:#ef4444;font-size:13px;">Lỗi tải dữ liệu: ${err.message}</div>`;
  }
}

function updateStockInfo(symbol, bar, prevBar) {
  const symEl   = document.getElementById('mkt-info-sym');
  const priceEl = document.getElementById('mkt-info-price');
  const chgEl   = document.getElementById('mkt-info-chg');
  const hEl     = document.getElementById('mkt-info-h');
  const lEl     = document.getElementById('mkt-info-l');
  const volEl   = document.getElementById('mkt-info-vol');
  const name    = STOCK_LIST.find(s => s.sym === symbol)?.name || '';

  if (symEl)   symEl.textContent  = symbol + (name ? ` · ${name}` : '');
  if (priceEl) priceEl.textContent = fmtNum(bar?.close, 0);
  if (hEl)     hEl.textContent     = fmtNum(bar?.high, 0);
  if (lEl)     lEl.textContent     = fmtNum(bar?.low, 0);
  if (volEl)   volEl.textContent   = fmtVol(bar?.volume);

  if (chgEl && bar && prevBar) {
    const chg = bar.close - prevBar.close;
    const pct = (chg / prevBar.close) * 100;
    const cls = colorClass(chg);
    chgEl.className = `mkt-info-change ${cls}`;
    chgEl.textContent = `${sign(chg)}${fmtNum(chg, 0)} (${sign(pct)}${fmtNum(pct, 2)}%)`;
  } else if (chgEl) {
    chgEl.className = 'mkt-info-change mkt-flat';
    chgEl.textContent = '—';
  }
  const updEl = document.getElementById('mkt-chart-updated');
  if (updEl) updEl.textContent = 'Cập nhật: ' + new Date().toLocaleTimeString('vi-VN');
}

function updateStockInfoEmpty(symbol) {
  const symEl = document.getElementById('mkt-info-sym');
  if (symEl) symEl.textContent = symbol;
  ['mkt-info-price','mkt-info-chg','mkt-info-h','mkt-info-l','mkt-info-vol'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.textContent = '—';
  });
}


function mktSetRange(r) {
  _currentRange = r;
  loadStockChart(_currentSym, r);
}


// ─── ML Prediction ───────────────────────────────────────────────────────────

async function loadMLPrediction(symbol) {
  const card = document.getElementById('mkt-pred-card');
  if (!card) return;

  // Show loading state
  card.innerHTML = `
    <div class="mkt-pred-card">
      <div class="mkt-pred-label">🤖 DỰ ĐOÁN ML</div>
      <div style="font-size:12px;color:#94a3b8;padding:12px 0;">Đang phân tích ${symbol}...</div>
    </div>`;

  try {
    const r = await fetch(`http://localhost:5000/ml/predict?symbol=${symbol}`);
    const j = await r.json();

    if (!j.ready || j.error) {
      card.innerHTML = `
        <div class="mkt-pred-card">
          <div class="mkt-pred-label">🤖 DỰ ĐOÁN ML</div>
          <div style="font-size:11px;color:#f59e0b;padding:8px 0;line-height:1.5;">
            ⚠ ${j.error || 'Model chưa sẵn sàng'}<br>
            <span style="color:#94a3b8;">Chạy: python3 ml/train_model.py</span>
          </div>
        </div>`;
      return;
    }

    const up    = j.direction_code > 0;
    const flat  = j.direction_code === 0;
    const color = up ? '#16a34a' : flat ? '#f59e0b' : '#dc2626';
    const arrow = up ? '▲' : flat ? '→' : '▼';
    const sign  = j.predicted_return >= 0 ? '+' : '';

    card.innerHTML = `
      <div class="mkt-pred-card">
        <div style="font-size:14px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#0b1220;margin-bottom:6px;">Dự Đoán Cổ Phiếu · ${j.symbol}</div>

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
    card.innerHTML = `
      <div class="mkt-pred-card">
        <div class="mkt-pred-label">DỰ ĐOÁN CỔ PHIẾU</div>
        <div style="font-size:11px;color:#ef4444;padding:8px 0;">Lỗi kết nối server</div>
      </div>`;
  }
}


async function initMarket() {
  injectMktStyles();
  ensureMarketUI();
  await refreshIndexPrices();
  setInterval(refreshIndexPrices, 60000);

  try {
    await loadScript(CHART_CDN);
    if (typeof LightweightCharts === 'undefined') throw new Error('LightweightCharts not loaded');
    await loadStockChart('VNM', '3M');

    setInterval(async () => {
      const updEl = document.getElementById('mkt-chart-updated');
      if (updEl) updEl.textContent = 'Đang cập nhật...';
      await loadStockChart(_currentSym, _currentRange);
    }, 5 * 60 * 1000);

  } catch (e) {
    console.error('[Market] Chart init error:', e);
    const chartEl = document.getElementById('mkt-stock-chart');
    if (chartEl) chartEl.innerHTML = `<div style="padding:40px;text-align:center;color:#ef4444;">Lỗi tải thư viện biểu đồ</div>`;
  }
}

document.addEventListener('DOMContentLoaded', initMarket);
