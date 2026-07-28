/* ===== Sharia Trading AI — frontend (glassmorphism) ===== */
const $ = (s, r = document) => r.querySelector(s);
const fmt = n => (n === null || n === undefined || n === '') ? '—' : Number(n).toLocaleString('id-ID');
const esc = s => (s ?? '').toString().replace(/&/g, '&amp;').replace(/</g, '&lt;');
const mdb = s => esc(s).replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/^\s*\*\s+/gm, '• ');
const api = async u => (await fetch(u)).json();
const post = async (u, b) => (await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json();
function toast(m){ const t=$('#toast'); t.textContent=m; t.style.display='block'; clearTimeout(t._h); t._h=setTimeout(()=>t.style.display='none',2600); }
let LAST_SCREEN = [];
let CURRENT_TICKERS = [];
const MANUAL_TK_KEY = 'sta_manual_tickers';

function normalizeTicker(raw){
  let t = (raw || '').toString().trim().toUpperCase();
  if(!t) return '';
  if(t.endsWith('.JK')) t = t.slice(0, -3);
  return t;
}

function getTicker(){
  return normalizeTicker($('#tk') && $('#tk').value);
}

function setTicker(tk){
  const el = $('#tk');
  if(!el) return;
  el.value = normalizeTicker(tk);
}

function loadManualTickers(){
  try{
    const raw = JSON.parse(localStorage.getItem(MANUAL_TK_KEY) || '[]');
    return Array.isArray(raw) ? raw.map(normalizeTicker).filter(Boolean) : [];
  }catch(_){ return []; }
}

function saveManualTicker(tk){
  tk = normalizeTicker(tk);
  if(!tk) return;
  if(CURRENT_TICKERS.includes(tk)) return; // sudah di funnel
  const list = [tk, ...loadManualTickers().filter(x => x !== tk)].slice(0, 12);
  localStorage.setItem(MANUAL_TK_KEY, JSON.stringify(list));
  renderManualChips();
  refreshTickerDatalist();
}

function clearManualTickers(){
  localStorage.removeItem(MANUAL_TK_KEY);
  renderManualChips();
  refreshTickerDatalist();
  toast('Riwayat ticker manual dihapus.');
}

function renderManualChips(){
  const box = $('#tk-manual-chips');
  if(!box) return;
  const manuals = loadManualTickers().filter(t => !CURRENT_TICKERS.includes(t));
  if(!manuals.length){
    box.innerHTML = '';
    return;
  }
  box.innerHTML = `<span class="mut" style="font-size:.72rem;margin-right:.15rem">Riwayat manual:</span>` +
    manuals.map(t => `<button type="button" class="badge na" style="cursor:pointer;font-size:.72rem;padding:3px 8px;border:1px solid var(--line);background:rgba(255,255,255,.04)" onclick="setTicker('${t}');analyze()">${esc(t)}</button>`).join('') +
    `<button type="button" class="mut" style="font-size:.68rem;cursor:pointer;background:none;border:none;text-decoration:underline;padding:0 4px" onclick="clearManualTickers()">hapus</button>`;
}

function refreshTickerDatalist(){
  const dl = $('#tk-list');
  if(!dl) return;
  const manuals = loadManualTickers();
  const seen = new Set();
  const opts = [];
  CURRENT_TICKERS.forEach(t => {
    if(seen.has(t)) return;
    seen.add(t);
    opts.push(`<option value="${esc(t)}">Funnel</option>`);
  });
  manuals.forEach(t => {
    if(seen.has(t)) return;
    seen.add(t);
    opts.push(`<option value="${esc(t)}">Manual</option>`);
  });
  dl.innerHTML = opts.join('');
}

function populateTickers(list, selectedTicker) {
  CURRENT_TICKERS = list.map(t => typeof t === 'string' ? normalizeTicker(t) : normalizeTicker(t.ticker)).filter(Boolean);
  refreshTickerDatalist();
  renderManualChips();
  const tickerVal = selectedTicker && (typeof selectedTicker === 'string' ? selectedTicker : selectedTicker.ticker);
  if (tickerVal) {
    setTicker(tickerVal);
  } else if (!getTicker() && CURRENT_TICKERS.length > 0) {
    setTicker(CURRENT_TICKERS[0]);
  }
}

function navigateStock(dir) {
  if (!CURRENT_TICKERS.length) { toast('Daftar funnel belum dimuat.'); return; }
  const cur = getTicker();
  let idx = CURRENT_TICKERS.indexOf(cur);
  if (idx < 0) idx = dir > 0 ? -1 : 0;
  idx = idx + dir;
  if (idx < 0) idx = CURRENT_TICKERS.length - 1;
  if (idx >= CURRENT_TICKERS.length) idx = 0;
  setTicker(CURRENT_TICKERS[idx]);
  analyze();
}

/* theme */
function toggleTheme(){ const r=document.documentElement; const t=r.getAttribute('data-theme')==='dark'?'light':'dark';
  r.setAttribute('data-theme',t); localStorage.setItem('theme',t); $('meta[name=theme-color]').setAttribute('content',t==='dark'?'#0f172a':'#eef2f7'); }
(function(){ const s=localStorage.getItem('theme'); if(s) document.documentElement.setAttribute('data-theme',s); })();

const TAB_INFOS = {
  dash: {
    title: "🏠 Dashboard (Pusat Keputusan)",
    desc: "Selamat datang di Pusat Keputusan! Tab ini berfungsi sebagai dashboard utama untuk memantau sinyal trading harian Anda. Di sini, Anda dapat melihat sinyal <b>BELI / HOLD / JUAL</b> yang dihasilkan secara otomatis oleh Funnel Kuantitatif berbasis aturan. Di bawahnya, Anda juga dapat memantau arah pasar IHSG (komponen M dalam CAN SLIM) untuk menghindari bertransaksi saat pasar sedang bearish, serta melihat Radar Kontradiksi TradingView untuk menyaring sinyal palsu."
  },
  analyze: {
    title: "🔎 Analisa Saham (Pusat Riset Emiten)",
    desc: "Masuk ke area riset saham aktif! Tab ini menggabungkan semua alat analisis dan penyaringan emiten syariah Anda. Gunakan sub-tab <b>Analisa Ticker</b> untuk mencari dan meminta saran naratif dari <b>Gemini / Advisor Lokal</b> tentang emiten tertentu. Butuh mencari peluang baru? Alihkan sub-tab ke <b>Screening</b> atau <b>Undervalue</b> untuk menyaring puluhan saham secara konvensional, hitung porsi modal dengan <b>Trading Plan</b>, atau pantau menu saham sore-pagi di sub-tab <b>BSJP</b>."
  },
  port: {
    title: "💼 Portofolio & Manajemen Modal",
    desc: "Kelola kemakmuran Anda di sini! Tab ini adalah tempat Anda memantau seluruh alokasi modal dan kepemilikan aset. Gunakan sub-tab <b>Portofolio RDN</b> untuk memantau kas di rekening broker riil, sub-tab <b>Simulasi</b> untuk mencatat histori kinerja paper trading (keakuratan prediksi), serta kelola kepemilikan pelindung nilai (safe-haven) Anda pada emas digital dan perak/dinar di sub-tab <b>Emas</b> dan <b>Perak</b>."
  },
  learn: {
    title: "📖 Pembelajaran & Standardisasi",
    desc: "Tingkatkan keahlian trading syariah Anda! Tab ini dirancang sebagai pustaka edukasi dan panduan kepatuhan. Anda dapat membaca modul kurikulum investasi di sub-tab <b>AI Learning</b>, memantau checklist rutinitas harian trading di sub-tab <b>Strategi Harian</b>, serta membaca standardisasi hukum investasi di sub-tab <b>Pedoman Syariah</b> berdasarkan Fatwa DSN-MUI."
  }
};

const SUB_TAB_INFOS = {
  // Analisa Saham
  "analyze-core": "🔎 <b>Analisa Ticker:</b> Pilih dari ~100 saham funnel, atau <b>ketik kode manual</b> (BEI / US dengan akhiran .US) untuk Analisa + Advisor on-demand. Gemini (gratis) atau Advisor Lokal.",
  "screen": "🧮 <b>Screening:</b> Lakukan penyaringan saham dari 75+ emiten syariah berdasarkan parameter Stochastic RSI, tren pergerakan harga, dan pola Golden Cross teknikal.",
  "underval": "💎 <b>Screener Undervalue:</b> Temukan saham syariah bervaluasi rendah (PBV/PER/PEG Graham murah) yang secara historis memiliki win-rate pembalikan arah (rebound) terbaik.",
  "investasi_saham": "🌟 <b>Investasi Saham:</b> Halaman evaluasi dan proyeksi dividen jangka panjang (ASII, SIDO, dll) untuk investasi tahunan non-trading.",
  "bsjp": "🌙 <b>BSJP:</b> Strategi 'Beli Sore Jual Pagi' (overnight trading) yang memantau kekuatan beli IEP di pre-closing untuk dilepas cepat di pre-opening pagi.",
  "plan": "📊 <b>Trading Plan:</b> Kalkulator alokasi dana per emiten menggunakan formula Money Management defensif dan strategi beli bertahap Taichi (OB1, OB2, OB3).",

  // Portofolio
  "port-core": "💼 <b>Portofolio RDN:</b> Pantau saldo rekening dana nasabah (RDN) riil Anda, hitung rasio alokasi tunai vs saham, serta pantau floating profit/loss posisi aktif.",
  "sim": "🧪 <b>Simulasi:</b> Rapor prediksi trading. Sistem merekam otomatis posisi rekomendasi beli harian dan melacak kinerjanya secara teratur untuk melatih adaptasi model AI.",
  "emas": "🥇 <b>Emas & Komoditas:</b> Catat dan pantau portofolio kepemilikan emas digital Anda di Tring Pegadaian lengkap dengan estimasi keuntungan/kerugian nilai riil.",
  "perak": "🪙 <b>Perak & Dinar:</b> Catat dan pantau alokasi kepemilikan perak dan koin dinar/dirham sebagai penyeimbang risiko portofolio saham.",

  // Pembelajaran
  "learn-core": "📖 <b>AI Learning:</b> Kurikulum materi trading pasar modal, panduan penggunaan dashboard, dan fitur pencatatan tingkat penyelesaian materi.",
  "strat": "📚 <b>Strategi Harian:</b> Checklist dan panduan tugas wajib harian trader dari pra-pembukaan bursa hingga pasca-penutupan bursa.",
  "ped": "📜 <b>Pedoman Syariah:</b> Standardisasi dan hukum investasi pasar modal syariah berdasarkan fatwa Dewan Syariah Nasional (DSN-MUI)."
};

/* tabs (+ lazy load) */
let _loaded = {};
document.querySelectorAll('.tab-btn-main').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab-btn-main').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
  t.classList.add('active'); $('#' + t.dataset.p).classList.add('active');
  const p = t.dataset.p;
  
  // Update banner info
  const info = TAB_INFOS[p];
  if(info) {
    const titleEl = $('#tab-info-title');
    const descEl = $('#tab-info-desc');
    if(titleEl) titleEl.textContent = info.title;
    if(descEl) descEl.innerHTML = info.desc;
  }
  
  if(p==='port') loadPortfolio();
  if(p==='learn') loadLearning();
  if(p==='dash' && !_loaded.cc){ loadCrossCheck(); }   // auto-load radar saat buka Dashboard
});

/* sub-tabs (+ lazy load) */
document.querySelectorAll('.sub-tab-btn').forEach(btn => {
  btn.onclick = () => {
    const parentPanel = btn.closest('.panel');
    parentPanel.querySelectorAll('.sub-tab-btn').forEach(x => x.classList.remove('active'));
    parentPanel.querySelectorAll('.sub-panel').forEach(x => x.classList.remove('active'));
    btn.classList.add('active');
    const subId = btn.dataset.sub;
    parentPanel.querySelector('#' + subId).classList.add('active');
    
    // Update banner info for sub-tab
    const subInfo = SUB_TAB_INFOS[subId];
    if(subInfo) {
      const mainActive = document.querySelector('.tab-btn-main.active');
      const mainTitle = mainActive ? mainActive.textContent.trim() : "";
      const subTitle = btn.textContent.trim();
      const titleEl = $('#tab-info-title');
      const descEl = $('#tab-info-desc');
      if(titleEl) titleEl.textContent = `${mainTitle} · Sub-Tab ${subTitle}`;
      if(descEl) descEl.innerHTML = subInfo;
    }
    
    // trigger lazy load
    if(subId==='port-core') loadPortfolio();
    if(subId==='investasi_saham') loadInvestasiSaham();
    if(subId==='sim') loadSimulation();
    if((subId==='emas'||subId==='perak') && !_loaded.cmd){ loadCommodities(); }
    if(subId==='bsjp') { loadBSJPSession(); }
  };
});

/* shared bits */
function pill(v, t, metricName, actualValue){ 
  const lbl = t || (v === true ? 'Lolos' : v === false ? 'Gagal' : 'n/a');
  const clickAttr = metricName ? `style="cursor:pointer;" onclick="explainMetric(document.getElementById('tk').value.trim().toUpperCase(), '${esc(metricName)}', '${v === true ? 'Lolos' : 'Gagal'}', '${esc(actualValue || '')}')"` : '';
  return `<span class="pill ${v===true?'ok':v===false?'no':'na'}" ${clickAttr}>${lbl}</span>`; 
}
function ring(pct, label, color){ const c = color || (pct>=66?'var(--buy)':pct>=40?'var(--hold)':'var(--sell)');
  return `<div class="ring" style="--p:${pct};--c:${c}"><div class="v"><b>${Math.round(pct)}</b><span>${label}</span></div></div>`; }
function ringScore(score, total, label){ const pct=total?score/total*100:0; const c=pct>=66?'var(--buy)':pct>=40?'var(--hold)':'var(--sell)';
  return `<div class="ring" style="--p:${pct};--c:${c}"><div class="v"><b>${score}<small style="font-size:.8rem;color:var(--mute)">/${total}</small></b><span>${label}</span></div></div>`; }
function bar(pct, gold){ return `<div class="bar ${gold?'gold':''}"><i style="width:${Math.max(3,Math.min(100,pct))}%"></i></div>`; }

/* ===================== MARKET ===================== */
let _mktChart = null;
let _mktData = null;
let _mktTimeframe = 'daily';

async function loadMarket(){
  try {
    const m = await api('/api/market');
    _mktData = m;
    renderMarketUI();
  } catch(e) {
    $('#mkt').innerHTML = '<span class="mut">Pasar n/a</span>';
  }
}

function renderMarketUI() {
  if (!_mktData || !_mktData.ok) {
    $('#mkt').innerHTML = '<span class="mut">Pasar n/a</span>';
    return;
  }
  const m = _mktData;
  window._marketTrend = m.trend;
  const up = m.trend === 'UPTREND';
  
  let usHtml = '';
  if (m.us && m.us.ok) {
    const usUp = m.us.trend === 'UPTREND';
    usHtml = `
      <div style="display:flex;align-items:center;gap:.7rem;margin-left:1rem;border-left:1px solid var(--line);padding-left:1rem">
        <span class="market-status-dot ${usUp?'open':'down'}"></span>
        <b>S&P 500</b> <span class="num">${fmt(m.us.price)}</span>
        <span class="num" style="color:${m.us.change_pct>=0?'var(--buy)':'var(--sell)'}">${m.us.change_pct>=0?'▲':'▼'}${Math.abs(m.us.change_pct)}%</span>
      </div>
    `;
  }

  $('#mkt').innerHTML = `
    <div style="display:flex;flex-direction:row;align-items:center;flex-wrap:wrap">
      <div style="display:flex;flex-direction:column;gap:.15rem;align-items:flex-start">
        <div style="display:flex;align-items:center;gap:.7rem">
          <span class="market-status-dot ${up?'open':'down'}"></span>
          <b>IHSG</b> <span class="num">${fmt(m.price)}</span>
          <span class="num" style="color:${m.change_pct>=0?'var(--buy)':'var(--sell)'}">${m.change_pct>=0?'▲':'▼'}${Math.abs(m.change_pct)}%</span>
        </div>
        ${m.now_wib ? `<div class="mut" style="font-size:.65rem;margin-left:1.4rem;line-height:1">${esc(m.now_wib)}</div>` : ''}
      </div>
      ${usHtml}
    </div>`;
    
  $('#mkt-body').innerHTML = `<div class="between">
    <div class="stat"><div class="lbl">IHSG</div><div class="big num ${up?'up':'down'}">${fmt(m.price)}</div>
      <div style="margin-top:.4rem">${badge(up?'BELI':'SELL', m.trend)} <span class="num" style="color:${m.change_pct>=0?'var(--buy)':'var(--sell)'}">${m.change_pct>=0?'+':''}${m.change_pct}%</span></div>
      ${m.now_wib ? `<div class="mut" style="font-size:.7rem;margin-top:.5rem;line-height:1.2">${esc(m.now_wib)}</div>` : ''}</div>
    <div style="text-align:right"><div class="lbl mut">SMA 200</div><div class="big num" style="font-size:1.1rem">${fmt(m.sma200)}</div>
      <div class="sub" style="max-width:240px">${esc(m.verdict)}</div></div></div>`;

  if (m.us && m.us.ok) {
    const usUp = m.us.trend === 'UPTREND';
    const usMktBody = $('#us-mkt-body');
    if (usMktBody) {
      usMktBody.innerHTML = `<div class="between">
        <div class="stat"><div class="lbl">S&P 500</div><div class="big num ${usUp?'up':'down'}">${fmt(m.us.price)}</div>
          <div style="margin-top:.4rem">${badge(usUp?'BELI':'SELL', m.us.trend)} <span class="num" style="color:${m.us.change_pct>=0?'var(--buy)':'var(--sell)'}">${m.us.change_pct>=0?'+':''}${m.us.change_pct}%</span></div>
          ${m.us.now_est ? `<div class="mut" style="font-size:.7rem;margin-top:.5rem;line-height:1.2">${esc(m.us.now_est)}</div>` : ''}</div>
        <div style="text-align:right"><div class="lbl mut">SMA 200</div><div class="big num" style="font-size:1.1rem">${fmt(m.us.sma200)}</div>
          <div class="sub" style="max-width:240px">${esc(m.us.verdict)}</div></div></div>`;
    }
  } else {
    const usMktBody = $('#us-mkt-body');
    if (usMktBody) {
      usMktBody.innerHTML = '<div class="empty">Data US Market tidak tersedia</div>';
    }
  }

  renderMktChart();
  renderUsMktChart();
}

function renderMktChart() {
  if (!_mktData) return;
  if (_mktChart) {
    try { _mktChart.remove(); } catch(e) {}
    _mktChart = null;
  }
  
  const m = _mktData;
  const isWeekly = _mktTimeframe === 'weekly';
  const closeSeries = isWeekly ? m.close_series_weekly : m.close_series_daily;
  const smaSeries = isWeekly ? m.sma200_series_weekly : m.sma200_series_daily;
  
  if (closeSeries && closeSeries.length) {
    const el = $('#mkt-chart');
    if (!el) return;
    el.innerHTML = ''; // bersihkan skeleton
    const LC = window.LightweightCharts;
    const dark = document.documentElement.getAttribute('data-theme') !== 'light';
    const txt = dark ? '#94a3b8' : '#475569';
    const grid = dark ? 'rgba(255,255,255,.03)' : 'rgba(15,23,42,.04)';
    const bd = dark ? '#334155' : '#cbd5e1';
    
    const base = {
      layout: { background: { color: 'transparent' }, textColor: txt, fontFamily: 'Outfit' },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: bd },
      timeScale: { borderColor: bd },
      crosshair: { mode: LC.CrosshairMode.Normal }
    };
    
    const chart = LC.createChart(el, {
      ...base,
      width: el.clientWidth,
      height: 140
    });
    
    const up = m.trend === 'UPTREND';
    const closeLine = chart.addLineSeries({
      color: up ? '#10b981' : '#ef4444',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: isWeekly ? 'IHSG (Pekan)' : 'IHSG'
    });
    closeLine.setData(closeSeries);
    
    if (smaSeries && smaSeries.length) {
      const smaLine = chart.addLineSeries({
        color: '#a78bfa',
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        title: isWeekly ? 'SMA 40 (W)' : 'SMA 200'
      });
      smaLine.setData(smaSeries);
    }
    
    chart.timeScale().fitContent();
    _mktChart = chart;
    
    try {
      window.removeEventListener('resize', handleMktChartResize);
    } catch(e) {}
    window.addEventListener('resize', handleMktChartResize);
  }
}

let _usMktChart = null;
let _usMktTimeframe = 'daily';

function renderUsMktChart() {
  if (!_mktData || !_mktData.us || !_mktData.us.ok) return;
  if (_usMktChart) {
    try { _usMktChart.remove(); } catch(e) {}
    _usMktChart = null;
  }
  
  const m = _mktData.us;
  const isWeekly = _usMktTimeframe === 'weekly';
  const closeSeries = isWeekly ? m.close_series_weekly : m.close_series_daily;
  const smaSeries = isWeekly ? m.sma200_series_weekly : m.sma200_series_daily;
  
  if (closeSeries && closeSeries.length) {
    const el = $('#us-mkt-chart');
    if (!el) return;
    el.innerHTML = ''; // bersihkan skeleton
    const LC = window.LightweightCharts;
    const dark = document.documentElement.getAttribute('data-theme') !== 'light';
    const txt = dark ? '#94a3b8' : '#475569';
    const grid = dark ? 'rgba(255,255,255,.03)' : 'rgba(15,23,42,.04)';
    const bd = dark ? '#334155' : '#cbd5e1';
    
    const base = {
      layout: { background: { color: 'transparent' }, textColor: txt, fontFamily: 'Outfit' },
      grid: { vertLines: { color: grid }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: bd },
      timeScale: { borderColor: bd },
      crosshair: { mode: LC.CrosshairMode.Normal }
    };
    
    const chart = LC.createChart(el, {
      ...base,
      width: el.clientWidth,
      height: 140
    });
    
    const up = m.trend === 'UPTREND';
    const closeLine = chart.addLineSeries({
      color: up ? '#10b981' : '#ef4444',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      title: isWeekly ? 'S&P 500 (Pekan)' : 'S&P 500'
    });
    closeLine.setData(closeSeries);
    
    if (smaSeries && smaSeries.length) {
      const smaLine = chart.addLineSeries({
        color: '#a78bfa',
        lineWidth: 1.5,
        priceLineVisible: false,
        lastValueVisible: false,
        title: isWeekly ? 'SMA 40 (W)' : 'SMA 200'
      });
      smaLine.setData(smaSeries);
    }
    
    chart.timeScale().fitContent();
    _usMktChart = chart;
    
    try {
      window.removeEventListener('resize', handleUsMktChartResize);
    } catch(e) {}
    window.addEventListener('resize', handleUsMktChartResize);
  }
}

function handleMktChartResize() {
  try {
    if (_mktChart && $('#mkt-chart')) {
      _mktChart.applyOptions({ width: $('#mkt-chart').clientWidth });
    }
  } catch(e) {}
}

function handleUsMktChartResize() {
  try {
    if (_usMktChart && $('#us-mkt-chart')) {
      _usMktChart.applyOptions({ width: $('#us-mkt-chart').clientWidth });
    }
  } catch(e) {}
}

function toggleMktChartTimeframe(tf) {
  _mktTimeframe = tf;
  const dailyBtn = document.getElementById('btn-mkt-daily');
  const weeklyBtn = document.getElementById('btn-mkt-weekly');
  
  if (tf === 'daily') {
    if (dailyBtn) dailyBtn.classList.add('active');
    if (weeklyBtn) weeklyBtn.classList.remove('active');
  } else {
    if (dailyBtn) dailyBtn.classList.remove('active');
    if (weeklyBtn) weeklyBtn.classList.add('active');
  }
  renderMktChart();
}

function toggleUsMktChartTimeframe(tf) {
  _usMktTimeframe = tf;
  const dailyBtn = document.getElementById('btn-us-mkt-daily');
  const weeklyBtn = document.getElementById('btn-us-mkt-weekly');
  
  if (tf === 'daily') {
    if (dailyBtn) dailyBtn.classList.add('active');
    if (weeklyBtn) weeklyBtn.classList.remove('active');
  } else {
    if (dailyBtn) dailyBtn.classList.remove('active');
    if (weeklyBtn) weeklyBtn.classList.add('active');
  }
  renderUsMktChart();
}
function badge(kind, txt){ const c=kind==='BELI'?'buy':kind==='SELL'?'sell':'hold'; return `<span class="badge ${c}">${esc(txt)}</span>`; }

async function loadUniverse(){ const d=await api('/api/universe'); $('#uni-count').textContent=d.jumlah;
  $('#uni-list').textContent = d.saham.slice(0,14).map(s=>s.ticker).join(' · ')+' …';
  const tickers = d.saham.map(s => s.ticker);
  populateTickers(tickers, 'ADRO');
  const planTick = $('#plan-ticker');
  if (planTick) {
    planTick.innerHTML = d.saham.map(s => `<option value="${s.ticker}">${s.ticker} - ${esc(s.nama_perusahaan || s.name || '')}</option>`).join('');
    setTimeout(loadPlanTicker, 100);
  }
}

async function loadDashMM(){
  try{ const b=await api('/api/portfolio/rdn'); const t=b.total;
    const hasGold = t.gold_value > 0;
    const gridCls = hasGold ? 'g-4' : 'g-3';
    let h=`<div class="grid ${gridCls}" style="gap:.8rem;margin-top:.5rem">
      ${miniStat('Ekuitas',fmt(t.equity),t.jumlah_rdn+' RDN · target '+t.target_emiten+' emiten')}
      ${miniStat('Cash',fmt(t.cash),(t.cash_pct??'–')+'% ekuitas')}
      ${miniStat('Aset Saham',fmt(t.asset_value),(t.asset_pct??'–')+'% ekuitas')}
      ${hasGold ? miniStat('Emas Digital',fmt(t.gold_value),(t.gold_pct??'–')+'% ekuitas') : ''}</div>`;
    if(b.rdn.length){
      const trend = window._marketTrend || 'UPTREND';
      const isUp = trend === 'UPTREND';
      h+=`<div class="grid g-2" style="gap:.7rem;margin-top:.8rem">`+b.rdn.map(r=>{
        if (r.broker === 'Tring Pegadaian') {
          const goldPlUp = (r.gold_pl || 0) >= 0;
          return `<div style="background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:10px;padding:.6rem .8rem">
            <div class="between"><b>🪙 ${esc(r.broker)}</b><span class="badge na" style="font-size:.65rem">Emas Digital</span></div>
            <div class="mut" style="font-size:.74rem;margin-top:.25rem">⚖️ Saldo <b>${r.gold_balance_grams}g</b> · 🪙 Nilai <b>${fmt(r.gold_value)}</b> (porsi ${r.gold_pct??'–'}% ekuitas)</div>
            <div class="mut" style="font-size:.74rem">💵 Modal <b>${fmt(r.gold_cost)}</b> · ${goldPlUp?'📈':'📉'} P/L Emas <b class="${goldPlUp?'pl-up':'pl-down'}">${goldPlUp?'+':''}${fmt(r.gold_pl)}</b> (${r.gold_pl_pct??'–'}%)</div>
          </div>`;
        }
        const a=r.advice||{};
        let subAdvice = '';
        if (r.broker === 'Profits Anywhere') {
          if (!isUp) {
            subAdvice = `<div style="margin-top:.45rem;padding:.35rem .45rem;border-radius:6px;background:rgba(234,179,8,.06);border:1px solid rgba(234,179,8,.15);font-size:.7rem;line-height:1.3">
              🟡 <b>Taktis (IHSG Downtrend)</b>: Amankan Cadangan <b>${fmt(a.reserve_fund)}</b> ke Emas Digital (Tring Pegadaian).
            </div>`;
          } else {
            subAdvice = `<div style="margin-top:.45rem;padding:.35rem .45rem;border-radius:6px;background:rgba(34,197,94,.06);border:1px solid rgba(34,197,94,.15);font-size:.7rem;line-height:1.3">
              🟢 <b>Taktis (IHSG Uptrend)</b>: Cairkan emas di Tring Pegadaian secara instan jika ada peluang BELI saham.
            </div>`;
          }
        }
        return `<div style="background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:10px;padding:.6rem .8rem">
          <div class="between"><b>${esc(r.broker)}</b><span class="badge ${r.emiten>=r.target_emiten?'buy':'warning'}">${r.emiten}/${r.target_emiten} emiten</span></div>
          <div class="mut" style="font-size:.74rem;margin-top:.25rem">💵 cash ${fmt(r.cash)} · 📦 aset ${fmt(r.asset_value)}${r.gold_value ? ` · 🪙 emas ${fmt(r.gold_value)}` : ''}</div>
          <div class="mut" style="font-size:.74rem">🧮 trading ${a.trading_fund_pct||50}% = ${fmt(a.trading_fund)} · siap deploy <b style="color:var(--buy)">${fmt(a.deployable_now)}</b> (${a.open_slots??'–'} slot)</div>
          ${a.reserve_fund ? `<div class="mut" style="font-size:.74rem;margin-top:.25rem;padding:.35rem .5rem;border-radius:6px;background:rgba(255,255,255,.02);border:1px dashed var(--line)">
            🛡️ <b>Alokasi Cadangan (${fmt(a.reserve_fund)})</b>: Emas Tring 60% = <b>${fmt(Math.round(a.reserve_fund * 0.6))}</b> · Cash/RDPU 40% = <b>${fmt(Math.round(a.reserve_fund * 0.4))}</b>
          </div>` : ''}
          ${subAdvice}</div>`;
      }).join('')+`</div>`;
    }
    h+=`<p class="sub" style="margin-top:.6rem">Sumber sama dengan tab Portofolio & Pusat Keputusan — saldo, aset, dan saran alokasi selalu konsisten.</p>`;
    $('#dash-mm-body').innerHTML=h;
  }catch(e){ $('#dash-mm-body').innerHTML='<p class="sub">Isi saldo cash RDN di tab Portofolio agar ringkasan Money Management muncul di sini.</p>'; }
}
async function loadDashROI(){
  try{ const d=await api('/api/portfolio/roi'); const I=d.integral, R=d.realized, U=d.unrealized;
    const ok=d.on_track, roiC=I.roi_pct>=0?'pl-up':'pl-down';
    const prog=Math.max(0,Math.min(100,(I.roi_pct/d.target_pct)*100));
    let h=`<div style="text-align:center;margin:.5rem 0 .3rem">
        <div class="num ${roiC}" style="font-size:2.1rem;font-weight:800;line-height:1">${I.roi_pct>=0?'+':''}${I.roi_pct}%</div>
        <div class="mut" style="font-size:.68rem">${fmt(I.pl)} / modal ${fmt(I.invested)}</div></div>
      <div class="grid g-2" style="gap:.5rem;margin:.4rem 0">
        <div class="cardlet" style="padding:.45rem .6rem"><div class="mut" style="font-size:.64rem">REALIZED (${R.n_trades})</div><b class="${(R.roi_pct||0)>=0?'pl-up':'pl-down'}" style="font-size:1rem">${R.roi_pct==null?'–':(R.roi_pct>=0?'+':'')+R.roi_pct+'%'}</b></div>
        <div class="cardlet" style="padding:.45rem .6rem"><div class="mut" style="font-size:.64rem">UNREALIZED</div><b class="${(U.roi_pct||0)>=0?'pl-up':'pl-down'}" style="font-size:1rem">${U.roi_pct>=0?'+':''}${U.roi_pct}%</b></div></div>
      <div class="between" style="font-size:.72rem"><span>Target <b>${d.target_pct}%</b></span><span class="${ok?'pl-up':'pl-down'}">${ok?'✓ on-track':'gap '+d.gap_to_target+'%'}</span></div>
      <div class="bar" style="height:8px;margin-top:.25rem"><i style="width:${prog}%;background:${ok?'var(--buy)':'var(--brand-2)'}"></i></div>
      <div style="margin-top:.55rem">${roiChart(d.curve, d.target_pct)}</div>`;
    $('#dash-roi-body').innerHTML=h;
  }catch(e){ $('#dash-roi-body').innerHTML='<p class="sub">Tambah posisi / tutup transaksi (Jual) untuk melihat ROI integral di sini.</p>'; }
}

/* ===================== DECISION CENTER ===================== */
let LAST_DECISIONS = null;

function bucket(css){ return css==='buy'?'buy':css==='sell'?'sell':'hold'; }  // warning→hold (tengah)
function funnelLed(state){
  const led=$('#funnel-led'), txt=$('#funnel-led-txt');
  if(!led) return;
  const map={run:['run','Proses…'], done:['done','Selesai ✓'], error:['run','Gagal'], idle:['','Siap']};
  const [cls,label]=map[state]||map.idle;
  led.className='led'+(cls?' '+cls:''); if(txt){ txt.className='led-txt'+(cls?' '+cls:''); txt.textContent=label; }
}

function buildFunnelMarkdown(d){
  if(!d) return '';
  const now=new Date().toLocaleString('id-ID',{timeZone:'Asia/Jakarta'});
  const lines=[];
  const bz=d.bursa||{};
  const us=bz.us||{};
  const ad=d.adaptive||{};
  const roiD=d.roi||{};
  const jml=d.jumlah||{};

  lines.push('# Hasil Funnel — Sharia Trading AI');
  lines.push('');
  lines.push(`> Dihasilkan · ${now} WIB`);
  lines.push('');
  lines.push(`**Universe ter-ranking:** ${d.jumlah_ranking??'—'} saham syariah  `);
  lines.push(`**Ringkasan aksi:** 🟢 BELI ${jml.buy??0} · 🟡 HOLD ${jml.hold??0} · 🔴 SELL ${jml.sell??0}`);
  lines.push('');

  // Status bursa
  lines.push('## Status Bursa');
  lines.push('');
  lines.push(`- **IDX:** ${bz.reason||'—'} · tren **${bz.trend||'—'}**${bz.now_wib?` · ${bz.now_wib}`:''}`);
  if(us && Object.keys(us).length){
    lines.push(`- **US:** ${us.reason||'—'} · tren **${us.trend||'—'}**${us.now_et?` · ${us.now_et}`:''}`);
  }
  lines.push('');

  if(roiD.integral){
    lines.push('## Adaptive Strategy (ROI)');
    lines.push('');
    lines.push(`- ROI Integral: **${roiD.integral.roi_pct}%** (target ${roiD.target_pct}%) · ${roiD.on_track?'on-track':`gap ${roiD.gap_to_target}%`}`);
    if(ad.min_buy_accuracy!=null){
      lines.push(`- Ambang akurasi BELI: **${ad.min_buy_accuracy}%** · TP net **${ad.take_profit_net_pct}%**`);
    }
    if(ad.notes && ad.notes[0]) lines.push(`- Catatan: ${_mdEscape(ad.notes[0])}`);
    lines.push('');
  }

  // Top 10
  const top10 = d.top10_detail || (d.top5_detail||[]).slice(0,10);
  lines.push('## Top 10 Saham Syariah Ter-ranking');
  lines.push('');
  lines.push('Skor Keyakinan = 40% Funnel + 30% Undervalue + 30% Akurasi Backtest.');
  lines.push('');
  lines.push('| Rank | Ticker | Nama | Keyakinan | Funnel | Sinyal | UV | Akurasi | ML | Status |');
  lines.push('|---:|---|---|---:|---:|---|---:|---:|---|---|');
  if(top10.length){
    top10.forEach((t,i)=>{
      const rank=t.rank||(i+1);
      const ml=t.ml_signal&&t.ml_signal.available?`${t.ml_signal.signal} ${Math.round((t.ml_signal.p_buy||0)*100)}%`:'—';
      lines.push(`| ${rank} | **${t.ticker}** | ${(t.name||'').replace(/\|/g,'/')} | ${t.conviction??'—'} | ${t.funnel_skor??'—'} | ${t.funnel_signal||'—'} | ${t.uv_score??'—'} | ${t.akurasi_pct??'—'}% | ${ml} | ${t.status||'—'} |`);
    });
  } else {
    lines.push('| — | — | — | — | — | — | — | — | — | — |');
  }
  lines.push('');

  function _decSection(title, emoji, list){
    lines.push(`## ${emoji} ${title} (${(list||[]).length})`);
    lines.push('');
    if(!list || !list.length){
      lines.push('_Tidak ada aksi pada kategori ini._');
      lines.push('');
      return;
    }
    list.forEach((x,i)=>{
      lines.push(`### ${i+1}. ${x.ticker}${x.action?` — ${x.action}`:''}`);
      lines.push('');
      if(x.urgency) lines.push(`- Urgensi: **${x.urgency}**`);
      if(x.confidence) lines.push(`- Keyakinan aksi: **${x.confidence}**`);
      if(x.conviction!=null) lines.push(`- Skor keyakinan: **${x.conviction}**`);
      if(x.akurasi_pct!=null) lines.push(`- Akurasi backtest: **${x.akurasi_pct}%**`);
      if(x.funnel_signal) lines.push(`- Sinyal funnel: ${x.funnel_signal}`);
      if(x.expected_return_pct!=null) lines.push(`- Ekspektasi return: ~${x.expected_return_pct}%`);
      const sm=x.size_mult ?? (x.details&&x.details.size_mult) ?? (x.alokasi&&x.alokasi.size_mult);
      if(sm!=null && sm!==1) lines.push(`- Regime size: **×${sm}**`);
      if(x.details&&(x.details.quality_score!=null||x.details.timing_score!=null)){
        lines.push(`- Quality/Timing: ${x.details.quality_score??'—'}/${x.details.timing_score??'—'}${x.details.final_score!=null?` · Final ${x.details.final_score}`:''}`);
      }
      if(x.reason) lines.push(`- Alasan: ${_mdEscape(x.reason)}`);
      if(x.next_step) lines.push(`- Langkah berikutnya: ${_mdEscape(x.next_step)}`);
      if(x.execution_timing) lines.push(`- Timing eksekusi: ${_mdEscape(x.execution_timing)}`);
      if(x.alokasi){
        const a=x.alokasi;
        if(a.tipe==='beli'){
          lines.push(`- Alokasi: RDN **${a.rdn||'—'}** · ~${a.lots??0} lot ≈ ${a.outlay_idr??a.nilai_idr??'—'} IDR${a.net_target_pct!=null?` · target jual +${a.net_target_pct}%`:''}${a.size_mult!=null&&a.size_mult!==1?` · size ×${a.size_mult}`:''}`);
          if(a.catatan) lines.push(`  - ${_mdEscape(a.catatan)}`);
        } else if(a.tipe==='realisasi'){
          lines.push(`- Realisasi: RDN **${a.rdn||'—'}** · ${a.lots??'—'} lot · nilai ${a.nilai??'—'} → bersih ${a.nilai_net??a.nilai??'—'}`);
        }
      }
      if(x.syariah_note) lines.push(`- Syariah: ${_mdEscape(x.syariah_note)}`);
      lines.push('');
    });
  }

  _decSection('Rekomendasi BELI / Add', '🟢', d.buy);
  _decSection('Rekomendasi HOLD', '🟡', d.hold);
  _decSection('Rekomendasi SELL / Exit', '🔴', d.sell);

  if(d.watch && d.watch.length){
    lines.push('## 🔄 Cadangan Rotasi / Watch');
    lines.push('');
    d.watch.forEach(w=>{
      lines.push(`- **${w.ticker}** (strength ${w.strength??'—'}): ${_mdEscape(w.reason||'')}`);
    });
    lines.push('');
  }

  if(d.strategi){
    const st=d.strategi;
    lines.push('## Target RDN & Rotasi');
    lines.push('');
    lines.push(`- Mode: ${st.mode} · target ${st.target_emiten} emiten/RDN`);
    lines.push(`- Dimiliki awal: ${st.dimiliki_awal} · dipertahankan: ${st.dipertahankan} · akan diisi: ${st.akan_diisi} · dipangkas: ${st.dipangkas} · rotasi: ${st.rotasi}`);
    (st.per_rdn||[]).forEach(r=>{
      lines.push(`- **${r.broker}**: ${r.perkiraan_setelah_aksi}/${st.target_emiten} · cash ${r.cash??0}${r.blokir_isi?' · ⚠ isi cash dulu':''}`);
    });
    lines.push('');
  }

  lines.push('---');
  lines.push('');
  lines.push('*Disclaimer: alat bantu keputusan, bukan ajakan jual/beli. Keputusan & risiko di tangan pengguna. Transaksi tunai, long-only, sesuai Fatwa DSN-MUI.*');
  lines.push('');
  return lines.join('\n');
}

function downloadFunnelMd(){
  if(!LAST_DECISIONS){ toast('Jalankan Funnel dulu di Pusat Keputusan.'); return; }
  const md=buildFunnelMarkdown(LAST_DECISIONS);
  downloadTextFile(`funnel_top10_${_mdStamp()}.md`, md);
  const j=LAST_DECISIONS.jumlah||{};
  toast(`Markdown Funnel diunduh (Top-10 · B${j.buy??0}/H${j.hold??0}/S${j.sell??0}).`);
}

async function runDecision(isAuto = false, opts = {}){
  // isAuto / opts.refresh===false → pakai cache server (≤30 mnt)
  // klik tombol / opts.refresh===true → hitung ulang data terbaru
  const forceRefresh = opts.refresh === true || (!isAuto && opts.refresh !== false && !opts.fromInit);
  if (window._funnelInterval) {
    clearInterval(window._funnelInterval);
  }
  window._funnelInterval = setInterval(() => runDecision(true, {refresh: false}), 30 * 60 * 1000);

  if (isAuto) {
    toast('🔄 Memuat keputusan funnel (cache periodik)…');
  } else if (forceRefresh) {
    toast('▶ Menghitung Funnel terbaru…');
  }

  funnelLed('run');
  const waitMsg = forceRefresh
    ? 'Menjalankan mesin keputusan (hitung ulang)… bisa ~1 menit (universe syariah)'
    : 'Memuat Pusat Keputusan (cache ≤30 mnt / prefetch jam bursa)…';
  $('#verdict').innerHTML=`<span class="spin"></span> <span class="dim">${waitMsg}</span>`;
  ['buy','hold','sell'].forEach(c=>$('#col-'+c).innerHTML='<div class="dc-empty">memuat…</div>');
  try{
    try {
      await Promise.all([loadMarket(), loadPortfolio()]);
    } catch(err) {
      console.warn("Segar data pasar/portofolio dilewati:", err);
    }
    const testMode=$('#test-mode')&&$('#test-mode').checked;
    const qs = new URLSearchParams();
    if (testMode) qs.set('force_open', 'true');
    if (forceRefresh) qs.set('refresh', 'true');
    const d=await api('/api/decisions'+(qs.toString()?('?'+qs.toString()):''));
    LAST_DECISIONS = d;
    const map={buy:d.buy,hold:d.hold,sell:d.sell};
    for(const c in map){
      $('#cnt-'+c).textContent=map[c].length;
      $('#col-'+c).innerHTML = map[c].length ? map[c].map(x=>decCard(x,c)).join('') : '<div class="dc-empty">tidak ada aksi</div>';
    }
    const t5d=d.top5_detail||(d.top5||[]).map(t=>({ticker:t}));
    const statusMap={BELI:['buy','BELI'],HOLD:['warning','HOLD'],JUAL:['sell','JUAL'],DIMILIKI:['na','dimiliki'],TERTAHAN:['na','tertahan']};
    const top5=t5d.map(t=>{ const c=t.conviction; const cc=c==null?'na':c>=55?'buy':c>=45?'warning':'sell';
      const sm=statusMap[t.status]||['na',t.status||''];
      const ml=t.ml_signal&&t.ml_signal.available?t.ml_signal:null;
      const mlTxt=ml?` · ML(h${ml.horizon||'-'}): ${ml.signal} ${(ml.p_buy!=null?Math.round(ml.p_buy*100)+'% BUY':'')}${ml.confident?' ✓':''}`:'';
      const tip=`Keyakinan gabungan ${c??'-'}% = funnel ${t.funnel_skor??'-'} (${t.funnel_signal||'-'}) · undervalue ${t.uv_score??'-'} · akurasi ${t.akurasi_pct??'-'}% · status ${sm[1]}${mlTxt}`;
      const mlCls=ml?(ml.signal==='BUY'?'buy':ml.signal==='SELL'?'sell':'warning'):'na';
      return `<span class="badge brand" style="cursor:pointer; font-size:.85rem; padding:.35rem .75rem; border-radius:8px; display:inline-flex; align-items:center; gap:.35rem;" title="${tip}" onclick="gotoAnalyze('${t.ticker}')">
        ${t.ticker}
        ${c!=null?`<span class="badge ${cc}" style="font-size:.65rem; padding:1px 4px; border-radius:4px;">${c}</span>`:''}
        ${t.status?`<span class="badge ${sm[0]}" style="font-size:.62rem; padding:1px 4px; border-radius:4px;">${sm[1]}</span>`:''}
        ${ml?`<span class="badge ${mlCls}" style="font-size:.62rem; padding:1px 4px; border-radius:4px;" title="Sinyal ML LightGBM horizon ${ml.horizon} hari — P(BUY) ${Math.round((ml.p_buy||0)*100)}%">🤖${ml.signal==='BUY'?'▲':ml.signal==='SELL'?'▼':'•'}${Math.round((ml.p_buy||0)*100)}</span>`:''}
      </span>`;
    }).join(' ');
    const top5Legend=`<div class="mut" style="font-size:.78rem; margin-top:.6rem; line-height:1.6">
      💡 <b>Skor Keyakinan</b> = 40% Funnel + 30% Undervalue + 30% Akurasi Backtest:
      <span class="badge buy" style="font-size:.68rem; padding:1px 5px;">≥55 Kuat</span> 
      <span class="badge warning" style="font-size:.68rem; padding:1px 5px;">45–54 Sedang</span> 
      <span class="badge sell" style="font-size:.68rem; padding:1px 5px;">&lt;45 Lemah</span> 
      <span class="mut">(Arahkan kursor / klik untuk detail)</span>
    </div>`;
    const bz=d.bursa; let bursaHtml='';
    if(bz){
      const us=bz.us||null;
      const trendBadge=(tr)=>{
        if(!tr) return '';
        const up=tr==='UPTREND';
        return `<span class="badge ${up?'buy':'sell'}" style="font-size:.68rem; padding:1px 5px;">${up?'▲':'▼'} ${esc(tr)}</span>`;
      };
      const row=(label, m, trend)=>{
        if(!m) return '';
        const open=!!m.open;
        const color=open?'var(--buy)':'#ca8a04';
        const icon=open?'🟢':'⏸';
        const tz=m.tz_label||'';
        let clock=m.now_local||m.now_et||m.now_wib||'';
        // US: tampilkan ET + padanan WIB; IDX: WIB saja
        if(m.market==='US' && m.now_et){
          clock = m.now_et + (m.now_wib?` · ${m.now_wib}`:'');
        } else if(m.market==='IDX' && m.now_wib){
          clock = m.now_wib;
        }
        const jam = (m.open_time&&m.close_time)
          ? ` · jam ${m.open_time}–${m.close_time} ${tz}`.trim()
          : '';
        const nx=m.next_holiday;
        const nxTxt=nx?` · Libur berikutnya: <b>${esc(nx.name)}</b> (${nx.date}${nx.in_days>=0?', '+nx.in_days+'h':''})`:'';
        const note=(!open && m.trading_day===false)
          ? ` — sinyal berbasis penutupan terakhir${m.last_trading_date?' ('+m.last_trading_date+')':''}`
          : '';
        const testTxt=(m.test_mode||bz.test_mode)?` <span class="badge brand" style="font-size:.65rem; padding:1px 5px;">🧪 Uji</span>`:'';
        return `<div style="margin-top:.45rem;">
          <div style="display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; margin-bottom:.15rem;">
            <b style="font-size:.82rem;">${esc(label)}</b> ${trendBadge(trend||m.trend)}
          </div>
          <div style="font-size:.84rem; line-height:1.4; color:${color}">
            ${icon} <b>${esc(m.reason||'—')}</b>
            ${clock?` <span class="mut" style="font-size:.74rem">· ${esc(clock)}${esc(jam)}</span>`:''}${testTxt}${note}${nxTxt}
          </div>
        </div>`;
      };
      bursaHtml = row('🇮🇩 Bursa IDX', bz, bz.trend) + row('🇺🇸 Bursa US', us, us&&us.trend);
    }
    const st=d.strategi;
    let stratHtml='';
    if(st){
      const rows=(st.per_rdn||[]).map(r=>{
        const acts=[];
        if(r.dipangkas) acts.push(`pangkas ${r.dipangkas}`);
        if(r.rotasi) acts.push('rotasi 1');
        if(r.akan_diisi) acts.push(`isi ${r.akan_diisi} slot`);
        if(r.blokir_isi) acts.push(`${r.slot_kosong} slot kosong — isi cash RDN dulu`);
        const full=r.perkiraan_setelah_aksi===st.target_emiten;
        return `<div style="margin-top:.4rem; font-size:.82rem; display:flex; align-items:center; gap:.45rem; flex-wrap:wrap;">
          <span class="badge ${full?'buy':'warning'}" style="font-size:.74rem; padding:2px 6px;">${esc(r.broker)} (${r.perkiraan_setelah_aksi}/${st.target_emiten})</span>
          <span class="mut">${acts.length ? acts.join(' · ') : 'stabil (tidak ada aksi)'}</span>
        </div>`;
      }).join('');
      stratHtml=`<div style="font-size: .88rem; line-height: 1.4; color: var(--text);">
        🎯 <b>Strategi Alokasi (${st.target_emiten} emiten/RDN)</b>:<br>
        <span class="dim" style="font-size:.78rem;">Dimiliki saat ini: ${st.dimiliki_awal} total emiten.</span>
        <div style="margin-top:.4rem;">${rows}</div>
      </div>`;
    }
    const watch=(d.watch||[]).map(w=>`<span class="badge na" title="${esc(w.reason||'')}" style="cursor:pointer; font-size:.78rem; padding:.25rem .55rem; border-radius:6px;" onclick="gotoAnalyze('${w.ticker}')">${w.ticker} (${w.strength})</span>`).join(' ');
    const mm=d.money_management; let mmHtml='';
    if(mm){
      const plCls = (mm.pl || 0) >= 0 ? 'pl-up' : 'pl-down';
      const plPrefix = (mm.pl || 0) >= 0 ? '+' : '';
      mmHtml=`<div style="font-size: .88rem; line-height: 1.5; color: var(--text);">
        💰 <b>Money Management</b>:<br>
        • Total Ekuitas: <b>${fmt(mm.equity)}</b><br>
        • Tunai (Cash RDN): <b>${fmt(mm.cash)}</b> (${mm.cash_pct ?? '—'}% ekuitas)<br>
        • Nilai Aset Saham: <b>${fmt(mm.asset_value)}</b> (${mm.asset_pct ?? '—'}% ekuitas)<br>
        • Jumlah Akun RDN: <b>${mm.jumlah_rdn} RDN</b><br>
        • Total P/L Berjalan: <span class="${plCls}"><b>${plPrefix}${fmt(mm.pl)}</b></span>
      </div>`;
    }
    const cacheMeta = d.cache || {};
    const ageSec = cacheMeta.age_seconds;
    const ageTxt = ageSec==null ? '' : (ageSec < 60 ? `${ageSec}s lalu` : `${Math.round(ageSec/60)} mnt lalu`);
    const cacheBadge = d.from_cache
      ? `<span class="badge na" style="font-size:.7rem;padding:2px 7px" title="Prefetch periodik jam bursa IDX">📦 Cache ${esc(ageTxt||'—')}</span>`
      : `<span class="badge buy" style="font-size:.7rem;padding:2px 7px">✨ Data baru ${esc(d.generated_at||'')}</span>`;
    const ad=d.adaptive, roiD=d.roi; let adHtml='';
    if(ad&&roiD){ 
      const plCls = roiD.integral.roi_pct >= 0 ? 'pl-up' : 'pl-down';
      const plPrefix = roiD.integral.roi_pct >= 0 ? '+' : '';
      const trackBadge = roiD.on_track 
        ? '<span class="badge buy" style="font-size:.72rem; padding:1px 5px;">on-track</span>' 
        : `<span class="badge warning" style="font-size:.72rem; padding:1px 5px;">gap ${roiD.gap_to_target}%</span>`;
      const basis = ad.based_on_simulations
        ? `${ad.based_on_simulations} simulasi`
        : `${ad.based_on_trades || 0} trades`;
      const noteLine = (ad.notes && ad.notes[0])
        ? `<div class="mut" style="font-size:.72rem; margin-top:.35rem; line-height:1.35">${esc(ad.notes[0])}</div>`
        : '';
      
      adHtml=`<div style="font-size: .88rem; line-height: 1.5; color: var(--text); margin-top: .6rem; border-top: 1px dashed var(--border); padding-top: .6rem;">
        📈 <b>Adaptive Strategy (ROI)</b>:<br>
        • Ambang Akurasi Beli: <b>${ad.min_buy_accuracy}%</b> · TP net <b>${ad.take_profit_net_pct}%</b><br>
        • ROI Integral: <span class="${plCls}"><b>${plPrefix}${roiD.integral.roi_pct}%</b></span> (Target ${roiD.target_pct}%) ${trackBadge}<br>
        • Basis: <b>${basis}</b>${ad.roi_basis?` · metrik <b>${esc(ad.roi_basis)}</b>`:''}
        ${noteLine}
      </div>`; 
    }
    
    $('#verdict').innerHTML=`
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:1rem; margin-bottom:1rem; flex-wrap:wrap; gap:1rem;">
        <div style="font-size:1.3rem; font-weight:800;">
          📋 Hasil Funnel: <span style="color:var(--brand);">${d.jumlah_ranking}</span> Saham Syariah Ter-ranking
          ${cacheBadge}
        </div>
        <div class="flex" style="gap:.6rem; flex-wrap:wrap; align-items:center;">
          <span class="badge buy" style="font-size:.9rem; padding:.35rem .85rem;">🟢 ${d.jumlah.buy} BELI</span>
          <span class="badge hold" style="font-size:.9rem; padding:.35rem .85rem;">🟡 ${d.jumlah.hold} HOLD</span>
          <span class="badge sell" style="font-size:.9rem; padding:.35rem .85rem;">🔴 ${d.jumlah.sell} SELL</span>
          <button class="btn secondary" style="font-size:.78rem; padding:.35rem .7rem" onclick="downloadFunnelMd()" title="Unduh Top-10 + BELI/HOLD/SELL sebagai Markdown">📥 MD Funnel</button>
        </div>
      </div>
      
      ${top5 ? `
      <div style="background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1rem; margin-bottom:1.2rem;">
        <div style="font-weight:700; font-size:1rem; margin-bottom:.5rem; display:flex; align-items:center; gap:.4rem;">
          🔥 Top-5 Watchlist Pilihan <span style="font-size:.8rem; font-weight:normal;" class="dim">(Skor Keyakinan Gabungan &amp; Status)</span>
        </div>
        <div style="margin-top:.6rem; display:flex; gap:.65rem; flex-wrap:wrap;">${top5}</div>
        ${top5Legend}
      </div>` : ''}

      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.2rem; margin-top: 1rem;">
        <!-- Card 1: Status Bursa IDX & US -->
        <div style="background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1.1rem; display:flex; flex-direction:column; gap:.35rem;">
          <div style="font-weight:700; font-size:.95rem; border-bottom:1px solid var(--border); padding-bottom:.4rem; color:var(--brand-2);">
            🌐 Status Bursa IDX &amp; US
          </div>
          ${bursaHtml}
          ${adHtml}
        </div>
        
        <!-- Card 2: Money Management -->
        <div style="background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1.1rem; display:flex; flex-direction:column; gap:.8rem;">
          <div style="font-weight:700; font-size:.95rem; border-bottom:1px solid var(--border); padding-bottom:.4rem; color:var(--brand-2);">
            💰 Ringkasan Modal (Money Management)
          </div>
          ${mmHtml}
        </div>
        
        <!-- Card 3: Alokasi & Rotasi -->
        <div style="background:var(--card); border:1px solid var(--border); border-radius:10px; padding:1.1rem; display:flex; flex-direction:column; gap:.8rem;">
          <div style="font-weight:700; font-size:.95rem; border-bottom:1px solid var(--border); padding-bottom:.4rem; color:var(--brand-2);">
            🎯 Target RDN &amp; Rotasi
          </div>
          ${stratHtml}
          ${watch ? `<div style="font-size:.82rem; margin-top:.3rem;"><span class="mut" style="font-weight:700; display:block; margin-bottom:.3rem;">🔄 Cadangan Rotasi:</span><div style="display:flex; gap:.4rem; flex-wrap:wrap;">${watch}</div></div>` : ''}
        </div>
      </div>

      <div style="margin-top: 1.2rem; border-top: 1px dashed var(--border); padding-top: .8rem; font-size: .78rem; line-height: 1.5; display: flex; gap: 1rem; flex-wrap: wrap;" class="mut">
        <span>🧠 <b>Skor Keyakinan Gabungan</b> = 40% Funnel + 30% Undervalue + 30% Akurasi.</span>
        <span>💰 <b>MM Icon</b> = alokasi Money Management per RDN.</span>
        <span>📊 <b>Konsistensi</b> = Urutan Top-5 diselaraskan dengan kolom BELI &amp; modul lainnya.</span>
      </div>`;
    funnelLed('done');
    
    const pList = [];
    const added = new Set();
    if (d.prioritized_tickers && d.prioritized_tickers.length > 0) {
      d.prioritized_tickers.forEach(x => {
        if (x.ticker === '🪙 EMAS' || x.ticker === 'EMAS') return;
        if (!added.has(x.ticker)) {
          pList.push({ ticker: x.ticker, akurasi_pct: x.akurasi_pct });
          added.add(x.ticker);
        }
      });
    }
    (d.top5 || []).forEach(t => { if (t !== '🪙 EMAS' && t !== 'EMAS' && !added.has(t)) { pList.push({ ticker: t, akurasi_pct: null }); added.add(t); } });
    (d.buy || []).forEach(x => { if (x.ticker !== '🪙 EMAS' && x.ticker !== 'EMAS' && !added.has(x.ticker)) { pList.push({ ticker: x.ticker, akurasi_pct: x.akurasi_pct }); added.add(x.ticker); } });
    (d.watch || []).forEach(x => { if (x.ticker !== '🪙 EMAS' && x.ticker !== 'EMAS' && !added.has(x.ticker)) { pList.push({ ticker: x.ticker, akurasi_pct: x.akurasi_pct }); added.add(x.ticker); } });
    (d.hold || []).forEach(x => { if (x.ticker !== '🪙 EMAS' && x.ticker !== 'EMAS' && !added.has(x.ticker)) { pList.push({ ticker: x.ticker, akurasi_pct: x.akurasi_pct }); added.add(x.ticker); } });
    (d.sell || []).forEach(x => { if (x.ticker !== '🪙 EMAS' && x.ticker !== 'EMAS' && !added.has(x.ticker)) { pList.push({ ticker: x.ticker, akurasi_pct: x.akurasi_pct }); added.add(x.ticker); } });
    CURRENT_TICKERS.forEach(t => {
      if (t !== '🪙 EMAS' && t !== 'EMAS' && !added.has(t)) {
        pList.push({ ticker: t, akurasi_pct: null });
        added.add(t);
      }
    });
    
    if (pList.length > 0) {
      const defaultTicker = d.top5 && d.top5.length > 0 ? d.top5[0] : pList[0].ticker;
      populateTickers(pList, defaultTicker);
      analyze();
    }
  }catch(e){ $('#verdict').innerHTML='<span style="color:var(--sell)">Gagal memuat.</span>'; funnelLed('error'); }
}
function decCard(x,c){ const u=x.urgency?` · ${x.urgency}`:''; const er=x.expected_return_pct?` · exp ~${x.expected_return_pct}%`:'';
  const cv=x.conviction, db=x.dividend_bonus;
  const conv = cv!=null
    ? `<span class="badge ${cv>=55?'buy':cv>=45?'warning':'sell'}" style="font-size:.56rem" title="skor keyakinan gabungan = funnel ${x.funnel_skor??'-'} (${x.funnel_signal||'-'}) + undervalue ${x.uv_score??'-'} + akurasi ${x.akurasi_pct??'-'}%${db?' + bonus dividen '+db:''}">🧠 ${cv}</span>`
    : (x.akurasi_pct!=null?`<span class="badge ${x.akurasi_pct>=55?'buy':x.akurasi_pct>=45?'warning':'sell'}" style="font-size:.56rem" title="akurasi prediksi (win-rate backtest)">🎯 ${x.akurasi_pct}%</span>`:'');
  const divBadge = x.context==='HOLD_DIVIDEN' ? '<span class="badge buy" style="font-size:.56rem" title="SELL ditunda demi dividen">💵 tahan dividen</span>'
    : (db>0?`<span class="badge na" style="font-size:.54rem" title="pembayar dividen rutin (+${db} skor)">💵 +${db}</span>`:'');
  const syariahBadge = x.syariah_note ? `<span class="badge buy" style="font-size:.56rem" title="${esc(x.syariah_note)}">✓ Syariah</span>` : '';
  const sm = x.size_mult ?? (x.details&&x.details.size_mult) ?? (x.alokasi&&x.alokasi.size_mult);
  const sizeBadge = (sm!=null && sm!==1)
    ? `<span class="badge ${sm<=0?'sell':'warning'}" style="font-size:.56rem" title="multiplier ukuran posisi dari regime IHSG/US">size ×${sm}</span>` : '';
  const comp = (x.funnel_signal||x.uv_score!=null||x.akurasi_pct!=null)
    ? `<div class="mut" style="font-size:.66rem;margin-top:.2rem">${x.funnel_signal?'funnel '+esc(x.funnel_signal):''}${x.uv_score!=null?' · UV '+x.uv_score:''}${x.akurasi_pct!=null?' · akurasi '+x.akurasi_pct+'%':''}${db>0?' · 💵 dividen +'+db:''}${(x.details&&x.details.quality_score!=null)?` · Q${x.details.quality_score}/T${x.details.timing_score??'—'}`:''}</div>` : '';
  const a=x.alokasi; let alloc='';
  const venueBadge = (x.details&&x.details.venue)
    ? `<span class="badge na" style="font-size:.56rem" title="venue eksekusi">📱 ${esc(x.details.venue)}</span>`
    : (a&&a.venue?`<span class="badge na" style="font-size:.56rem">📱 ${esc(a.venue)}</span>`:'');
  if(a){
    const unit=(a.currency==='USD'||(a.shares_per_lot===1))?'lembar':'lot';
    const cur=a.currency==='USD'?'USD ':'';
    if(a.tipe==='beli' && a.lots>0) alloc=`<div class="mut" style="margin-top:.3rem;font-size:.7rem">💰 <b>${esc(a.rdn||a.venue||'')}</b>: ~${a.lots} ${unit} ≈ ${cur}${fmt(a.outlay_idr||a.nilai_idr)} <span title="termasuk biaya beli">incl. fee</span>${a.pct_cash!=null?` (${a.pct_cash}% cash)`:''}${a.net_target_pct!=null?` · jual <b>+${a.net_target_pct}%</b>`:''}${a.size_mult!=null&&a.size_mult!==1?` · size ×${a.size_mult}`:''}${a.sesuai_portofolio?' · ✓ sesuai portofolio':''}</div>`;
    else if(a.tipe==='beli') alloc=`<div class="mut" style="margin-top:.3rem;font-size:.7rem">💰 ${esc(a.catatan)}</div>`;
    else if(a.tipe==='realisasi') alloc=`<div class="mut" style="margin-top:.3rem;font-size:.7rem">💰 ${esc(a.rdn||'')} · jual portofolio ${a.lots} ${unit}: ${cur}${fmt(a.nilai)} <span title="nilai pasar kotor">kotor</span> → <b style="color:var(--buy)">${cur}${fmt(a.nilai_net??a.nilai)}</b> <span title="hasil yg masuk cash, stlh fee jual">bersih</span>${a.sesuai_portofolio?' · ✓ sesuai portofolio':''}</div>`;
  }
  const ep=x.exit_plan; let exitHtml='';
  if(ep && ep.lots_total>0){
    const rows=(ep.stages||[]).map(s=>{
      let v='';
      if(s.nilai_net!=null) v=` @ ${fmt(s.harga)} ≈ <b style="color:var(--buy)">${fmt(s.nilai_net)}</b> bersih <span class="mut">(${fmt(s.nilai)} kotor)</span>`;
      else if(s.skenario_impas){ v=` — impas @ ${fmt(s.skenario_impas.harga)} ≈ <b style="color:var(--buy)">${fmt(s.skenario_impas.nilai_net)}</b> bersih / cut @ ${fmt(s.skenario_cut.harga)} ≈ <b>${fmt(s.skenario_cut.nilai_net)}</b> bersih`; }
      return `<div>• <b>Tahap ${s.tahap}: jual ${s.lots} lot</b>${v} <span class="mut">(${esc(s.kapan)})</span></div><div class="mut" style="font-size:.66rem;margin-left:.7rem">${esc(s.patokan)}</div>`;
    }).join('');
    exitHtml=`<div style="margin-top:.35rem;font-size:.72rem;background:rgba(239,68,68,.08);border:1px solid var(--line);border-radius:9px;padding:.45rem .6rem">
      🧮 <b>Rencana Exit</b> (${esc(ep.style)}): <b>${ep.lots_now}/${ep.lots_total} lot sekarang</b>${ep.lots_rest>0?`, sisa ${ep.lots_rest} lot`:''}${ep.total_nilai_net_now!=null?` · jual semua kini ≈ <b style="color:var(--buy)">${fmt(ep.total_nilai_net_now)}</b> bersih${ep.total_nilai_now!=null?` (${fmt(ep.total_nilai_now)} kotor)`:''}`:''}
      <div class="mut" style="margin-top:.25rem">${rows}</div>
      <div class="mut" style="margin-top:.2rem">Impas ${fmt(ep.breakeven_price)} · cut-loss ${fmt(ep.cut_loss_price)} (−7%) · nilai = bersih stlh fee jual ${ep.fee_sell_pct}%</div></div>`;
  }
  
  // Strategy AI Verdict Card (Zeta AI Style)
  const v = x.ai_verdict;
  let aiVerdictHtml = '';
  if (v && typeof v === 'object') {
    const rec = v.rekomendasi_claude || v.rekomendasi || '';
    const keyak = v.keyakinan || '';
    const entry = v.entry_ideal || v.entry_pre_closing || '';
    const tp = v.target_harga || v.target_pre_opening || '';
    const sl = v.stop_loss || '';
    const risk = v.risiko_utama || '';
    const justification = v.justifikasi_teknikal || v.alasan_utama || '';
    
    const recClass = /STRONG BUY|^BUY|ACCUMULATE/.test(rec.toUpperCase()) ? 'buy' : /AVOID|SELL/.test(rec.toUpperCase()) ? 'sell' : 'hold';
    
    aiVerdictHtml = `
      <div style="margin-top: .6rem; padding: .65rem; background: rgba(59, 130, 246, 0.04); border: 1px solid rgba(59, 130, 246, 0.15); border-radius: 8px; font-size: .74rem; line-height: 1.4;">
        <div style="font-weight: 700; color: var(--brand-2); display: flex; align-items: center; justify-content: space-between; margin-bottom: .3rem;">
          <span style="display: flex; align-items: center; gap: .3rem;">🧠 Strategy AI Verdict</span>
          <span class="badge ${recClass}" style="font-size: .64rem; padding: 1px 5px;">${esc(rec)} (${esc(keyak)})</span>
        </div>
        ${justification ? `<div style="color: var(--text); font-style: italic; margin-bottom: .4rem; border-left: 2px solid var(--brand); padding-left: 5px;">"${esc(justification)}"</div>` : ''}
        <div style="display: flex; gap: .8rem; flex-wrap: wrap; margin-bottom: .2rem;">
          ${entry ? `<span>Entry: <b>Rp ${Number(entry).toLocaleString('id-ID')}</b></span>` : ''}
          ${tp ? `<span>TP: <b>Rp ${Number(tp).toLocaleString('id-ID')}</b></span>` : ''}
          ${sl ? `<span>SL: <b style="color: var(--sell)">Rp ${Number(sl).toLocaleString('id-ID')}</b></span>` : ''}
        </div>
        ${risk ? `<div style="color: var(--text-muted); font-size: .68rem; margin-top: .2rem;"><span style="color: var(--accent-red); font-weight: 600;">⚠️ Risiko:</span> ${esc(risk)}</div>` : ''}
      </div>
    `;
  }

  const isGold = x.ticker==='🪙 EMAS'||x.ticker==='EMAS';
  return `<div class="decision-card ${c}" onclick="gotoAnalyze('${x.ticker}')">
    <div class="dc-top"><span class="tkr${isGold?' tkr-emas':''}">${x.ticker}</span><div class="flex" style="gap:.3rem">${syariahBadge}${venueBadge}${sizeBadge}${divBadge}${conv}<span class="badge ${c}" style="font-size:.6rem">${esc(x.action)}${u}</span></div></div>
    <div class="meta" style="display:block"><div>${esc(x.reason)}</div>
      ${comp}
      ${alloc}
      ${exitHtml}
      ${aiVerdictHtml}
      <div class="mut" style="margin-top:.25rem">
        → ${esc(x.next_step||'')}
        ${x.execution_timing ? `<br><span class="badge warning" style="font-size:.65rem;margin-top:.35rem;display:inline-block;background:rgba(234,179,8,.08);color:#ca8a04;border:1px solid rgba(234,179,8,.2)">⏱ Eksekusi${x.execution_market?` ${esc(x.execution_market)}`:''}: ${esc(x.execution_timing)}</span>` : ''}
        ${er}
      </div></div></div>`; }
function dcard(s,c){ const isGold = s.ticker==='🪙 EMAS'||s.ticker==='EMAS';
  return `<div class="decision-card ${c}" onclick="gotoAnalyze('${s.ticker}')">
  <div class="dc-top"><span class="tkr${isGold?' tkr-emas':''}">${s.ticker}</span><span class="badge ${s.css||'na'}" style="font-size:.62rem">${esc(s.final_signal||s.aksi)}</span></div>
  <div class="meta"><span>${esc(s.sector||'')}</span><span>6M ${s.magic_score}/6</span><span>CS ${s.canslim_score}/7</span>
    <span>J7 ${s.jalur7_score??'-'}/4</span><span>skor ${s.skor}</span></div></div>`; }

/* ===================== ANALISA ===================== */
let LAST_ANALYZE = null;
let LAST_ADVISOR = null;

function aiSlot(){ let s=$('#ai-slot'); if(!s){ s=document.createElement('div'); s.id='ai-slot'; $('#aout').prepend(s);} return s; }

function downloadTextFile(filename, text, mime){
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([text],{type: mime||'text/markdown;charset=utf-8'}));
  a.download=filename;
  a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 1500);
}

function _mdEscape(s){
  return String(s??'').replace(/\r\n/g,'\n');
}

function _mdYesNo(v){
  if(v===true) return '✓ Lolos';
  if(v===false) return '✕ Gagal';
  return '—';
}

function buildAnalyzeMarkdown(d){
  if(!d) return '';
  const now=new Date().toLocaleString('id-ID',{timeZone:'Asia/Jakarta'});
  const rec=d.rekomendasi||{}, sh=d.sharia||{}, f=d.fundamental||{}, c=d.canslim||{}, t=d.technical||{}, b=d.bandarmologi;
  const lines=[];
  lines.push(`# Analisa Saham Syariah — ${d.ticker}`);
  lines.push('');
  lines.push(`> Dihasilkan oleh Sharia Trading AI · ${now} WIB`);
  lines.push('');
  lines.push(`**Nama:** ${d.name||'—'}  `);
  lines.push(`**Sektor:** ${d.sector||'—'}  `);
  lines.push(`**Mode:** ${d.input_mode==='manual'||d.in_funnel_universe===false?'Manual (di luar funnel)':'Universe funnel'}  `);
  lines.push(`**Syariah:** ${sh.compliant?'✓ Lolos DES/ISSI':'✕ Non-syariah'}${sh.des_status==='outside_curated'?' (verifikasi DES mandiri)':''}  `);
  lines.push(`**Rekomendasi:** ${rec.final_signal||rec.aksi||'—'}  `);
  lines.push(`**Skor Funnel:** ${rec.skor??'—'}/100`);
  if(d.data_notes && d.data_notes.length){
    lines.push(`**Catatan data:** ${d.data_notes.map(_mdEscape).join(' · ')}`);
  }
  lines.push('');
  if(rec.alasan && rec.alasan.length){
    lines.push('## Alasan Rekomendasi');
    lines.push('');
    rec.alasan.forEach(a=>lines.push(`- ${_mdEscape(a)}`));
    lines.push('');
  }
  const sc=rec.scoring;
  if(sc && sc.model==='layered'){
    const reg=sc.regime||{};
    lines.push('## Skor Dua Lapis');
    lines.push('');
    lines.push(`- Model: **layered** · Keputusan: **${sc.keputusan||'—'}** · Final: **${sc.final_score??sc.skor??'—'}**/100 · Eligible BELI: **${sc.eligible_for_buy?'Ya':'Tidak'}** · Multiplier: **×${sc.size_mult??1}**`);
    lines.push(`- Quality: **${sc.quality_score??'—'}**/100 · Timing: **${sc.timing_score??'—'}**/100${sc.timing_layak_entry?' (layak entry)':' (tunggu ≥65)'}${sc.timing_bonus?` · bonus ${sc.timing_bonus}`:''}`);
    lines.push(`- Regime: **${reg.regime||'—'}** ${reg.label?`— ${_mdEscape(reg.label)}`:''}${reg.pct_vs_sma200!=null?` (${reg.pct_vs_sma200}% vs SMA200)`:''}`);
    lines.push('');
    const gates=(sc.gates&&sc.gates.gates)||[];
    if(gates.length){
      lines.push('| Gate | Status | Detail |');
      lines.push('|---|---|---|');
      gates.forEach(g=>{
        lines.push(`| ${g.nama||g.id||'—'} | ${g.passed?'✓ Lolos':'✕ Gagal'} | ${_mdEscape(g.detail||'')} |`);
      });
      lines.push('');
    }
    const comps=sc.components||{};
    const keys=Object.keys(comps);
    if(keys.length){
      lines.push('| Komponen | Nilai | Bobot | Kontribusi |');
      lines.push('|---|---:|---:|---:|');
      keys.forEach(k=>{
        const c=comps[k];
        lines.push(`| ${k} | ${Math.round((c.nilai||0)*100)} | ${Math.round((c.bobot||0)*100)}% | ${c.kontribusi??'—'} |`);
      });
      lines.push('');
    }
  }
  lines.push('## 1. Screening Syariah');
  lines.push('');
  lines.push(`- Compliant: **${sh.compliant?'Ya':'Tidak'}**`);
  if(sh.in_des!=null) lines.push(`- Dalam DES/ISSI: **${sh.in_des?'Ya':'Tidak'}**`);
  if(sh.notes) lines.push(`- Catatan: ${_mdEscape(Array.isArray(sh.notes)?sh.notes.join('; '):sh.notes)}`);
  lines.push('');
  lines.push('## 2. 6 Magic Number');
  lines.push('');
  lines.push(`Skor: **${f.magic_score??'—'}/6** · Verdict: **${f.verdict||'—'}** · Sumber: \`${f.source||'—'}\``);
  lines.push('');
  lines.push('| Kriteria | Nilai | Target | Status |');
  lines.push('|---|---|---|---|');
  (f.checks||[]).forEach(cr=>{
    lines.push(`| ${cr.kriteria||''} | ${cr.nilai??'—'} | ${cr.target??'—'} | ${_mdYesNo(cr.lolos)} |`);
  });
  if(f.bonus_dividend){
    const bd=f.bonus_dividend;
    lines.push(`| ${bd.kriteria||'Dividend Yield'} (bonus) | ${bd.nilai??'—'} | ${bd.target??'—'} | ${_mdYesNo(bd.lolos)} |`);
  }
  lines.push('');
  lines.push('## 3. CAN SLIM');
  lines.push('');
  lines.push(`Skor: **${c.canslim_score??'—'}/7** · Verdict: **${c.verdict||'—'}**`);
  lines.push('');
  lines.push('| Letter | Kriteria | Nilai | Status |');
  lines.push('|---|---|---|---|');
  const letters=c.letters||{};
  Object.keys(letters).forEach(k=>{
    const L=letters[k];
    lines.push(`| **${k}** | ${L.kriteria||''} | ${L.nilai??'—'} | ${_mdYesNo(L.lolos)} |`);
  });
  lines.push('');
  lines.push('## 4. Teknikal');
  lines.push('');
  if(t.ok){
    lines.push(`- Harga: **${t.price??'—'}**`);
    lines.push(`- Tren: **${t.trend||'—'}** · Bias: ${t.bias||'—'}`);
    lines.push(`- vs SMA200: ${t.sma?.price_vs_sma200||'—'} (SMA200 ${t.sma?.sma200??'—'})`);
    if(t.stochastic){
      lines.push(`- Stochastic: %K ${t.stochastic.k??'—'} · zona ${t.stochastic.zona||'—'} · ${t.stochastic.sinyal||'—'}`);
    }
    lines.push(`- Support: ${t.support??'—'} · Resistance: ${t.resistance??'—'}`);
    if(t.adx) lines.push(`- ADX: ${t.adx.value??'—'} (${t.adx.strength||'—'})`);
    if(t.atr) lines.push(`- ATR: ${t.atr.value??'—'} (${t.atr.pct??'—'}%) · SL ${t.atr.sl_2atr??'—'} · TP ${t.atr.tp_4atr??'—'}`);
    if(t.candlestick?.length) lines.push(`- Pola candle: ${t.candlestick.join(', ')}`);
    if(t.entry_signals?.length){
      lines.push('');
      lines.push('### Sinyal Entry');
      lines.push('');
      t.entry_signals.forEach(s=>{
        lines.push(`- **${s.kode}** — ${s.nama}: ${_mdEscape(s.detail||'')}${s.volume_konfirmasi?' · volume kuat':''}`);
      });
    } else {
      lines.push('- Belum ada sinyal entry pada candle terakhir.');
    }
  } else {
    lines.push(`Data teknikal tidak cukup${t.error?`: ${_mdEscape(t.error)}`:'.'}`);
  }
  lines.push('');
  if(b){
    lines.push('## 5. Bandarmologi');
    lines.push('');
    lines.push(`- Sentiment: **${b.sentiment||'—'}** (skor ${b.score??'—'}/100)`);
    if(b.note) lines.push(`- Catatan: ${_mdEscape(b.note)}`);
    lines.push('');
  }
  if(d.jalur7 && d.jalur7.ok){
    const j=d.jalur7;
    lines.push('## 6. Jalur 7%');
    lines.push('');
    lines.push(`- Layak: **${j.layak?'Ya':'Tidak'}** · Skor: ${j.score??'—'}`);
    if(j.catatan) lines.push(`- ${_mdEscape(Array.isArray(j.catatan)?j.catatan.join('; '):j.catatan)}`);
    lines.push('');
  }
  lines.push('---');
  lines.push('');
  lines.push('*Disclaimer: alat bantu analisa, bukan ajakan jual/beli. Keputusan & risiko di tangan pengguna. Transaksi tunai, long-only, sesuai Fatwa DSN-MUI.*');
  lines.push('');
  return lines.join('\n');
}

function buildAdvisorMarkdown(adv, analyze){
  if(!adv) return '';
  const now=new Date().toLocaleString('id-ID',{timeZone:'Asia/Jakarta'});
  const tk=adv.ticker || (analyze&&analyze.ticker) || 'SAHAM';
  const v=adv.verdict||{};
  const lines=[];
  lines.push(`# Advisor — ${tk} (${(adv.engine||'—').toString().toUpperCase()})`);
  lines.push('');
  lines.push(`> Dihasilkan oleh Sharia Trading AI · ${now} WIB`);
  lines.push('');
  lines.push(`**Engine:** ${adv.engine||'—'}  `);
  lines.push(`**Model:** ${adv.model||'—'}  `);
  if(adv.fallback_dari) lines.push(`**Fallback dari:** ${adv.fallback_dari}  `);
  if(adv.rekomendasi_mesin){
    const rm=adv.rekomendasi_mesin;
    lines.push(`**Rekomendasi mesin:** ${rm.final_signal||rm.aksi||'—'} (skor ${rm.skor??'—'})`);
  }
  lines.push('');
  if(v && Object.keys(v).length){
    lines.push('## Verdict');
    lines.push('');
    const rec=v.rekomendasi_claude||v.rekomendasi||'—';
    lines.push(`- **Rekomendasi:** ${rec}`);
    if(v.keyakinan) lines.push(`- **Keyakinan:** ${v.keyakinan}`);
    if(v.vs_mesin) lines.push(`- **vs Mesin:** ${String(v.vs_mesin).replace(/_/g,' ')}`);
    if(v.penyesuaian_conviction!=null) lines.push(`- **Penyesuaian conviction:** ${v.penyesuaian_conviction}`);
    if(v.entry_ideal!=null) lines.push(`- **Entry ideal:** ${v.entry_ideal}`);
    if(v.stop_loss!=null) lines.push(`- **Stop loss:** ${v.stop_loss}`);
    if(v.target_harga!=null) lines.push(`- **Target:** ${v.target_harga}`);
    if(v.rrr) lines.push(`- **RRR:** ${v.rrr}`);
    if(v.horizon) lines.push(`- **Horizon:** ${v.horizon}`);
    if(v.risiko_utama) lines.push(`- **Risiko utama:** ${v.risiko_utama}`);
    lines.push('');
  }
  lines.push('## Analisa Naratif');
  lines.push('');
  lines.push(_mdEscape(adv.analisa||'(kosong)'));
  lines.push('');
  if(adv.usage){
    const u=adv.usage;
    const parts=[];
    if(u.input_tokens) parts.push(`${u.input_tokens} token input`);
    if(u.output_tokens) parts.push(`${u.output_tokens} token output`);
    if(u.durasi_detik) parts.push(`${u.durasi_detik}s`);
    if(parts.length){
      lines.push('---');
      lines.push(`*Usage: ${parts.join(' · ')}*`);
      lines.push('');
    }
  }
  lines.push('---');
  lines.push('');
  lines.push('*Disclaimer: alat bantu analisa, bukan ajakan jual/beli. Keputusan & risiko di tangan pengguna.*');
  lines.push('');
  return lines.join('\n');
}

function downloadAnalyzeMd(){
  if(!LAST_ANALYZE){ toast('Jalankan Analisa dulu.'); return; }
  const tk=LAST_ANALYZE.ticker||'SAHAM';
  const md=buildAnalyzeMarkdown(LAST_ANALYZE);
  downloadTextFile(`analisa_${tk}_${_mdStamp()}.md`, md);
  toast(`Markdown Analisa ${tk} diunduh.`);
}

function _advisorEngineSlug(adv){
  const eng = ((adv && adv.engine) || '').toString().toLowerCase().trim();
  if(eng === 'gemini' || eng === 'deepseek' || eng === 'lokal') return eng;
  // fallback dari nama model bila engine kosong
  const model = ((adv && adv.model) || '').toString().toLowerCase();
  if(model.includes('deepseek')) return 'deepseek';
  if(model.includes('gemini')) return 'gemini';
  if(model.includes('lokal') || model.includes('local')) return 'lokal';
  return 'advisor';
}

function downloadAdvisorMd(){
  if(!LAST_ADVISOR){ toast('Jalankan Advisor dulu.'); return; }
  const tk=LAST_ADVISOR.ticker||(LAST_ANALYZE&&LAST_ANALYZE.ticker)||'SAHAM';
  const eng=_advisorEngineSlug(LAST_ADVISOR);
  const md=buildAdvisorMarkdown(LAST_ADVISOR, LAST_ANALYZE);
  downloadTextFile(`advisor_${eng}_${tk}_${_mdStamp()}.md`, md);
  toast(`Markdown Advisor ${eng.toUpperCase()} · ${tk} diunduh.`);
}

function downloadAnalyzeAdvisorMd(){
  if(!LAST_ANALYZE && !LAST_ADVISOR){ toast('Jalankan Analisa / Advisor dulu.'); return; }
  const tk=(LAST_ANALYZE&&LAST_ANALYZE.ticker)||(LAST_ADVISOR&&LAST_ADVISOR.ticker)||'SAHAM';
  const parts=[];
  if(LAST_ANALYZE) parts.push(buildAnalyzeMarkdown(LAST_ANALYZE));
  if(LAST_ADVISOR){
    if(parts.length) parts.push('\n\n---\n\n');
    parts.push(buildAdvisorMarkdown(LAST_ADVISOR, LAST_ANALYZE));
  }
  const eng = LAST_ADVISOR ? _advisorEngineSlug(LAST_ADVISOR) : 'analisa';
  const fname = LAST_ADVISOR
    ? `analisa_advisor_${eng}_${tk}_${_mdStamp()}.md`
    : `analisa_${tk}_${_mdStamp()}.md`;
  downloadTextFile(fname, parts.join(''));
  toast(`Markdown gabungan ${LAST_ADVISOR?eng.toUpperCase()+' · ':''}${tk} diunduh.`);
}

function _mdStamp(){
  const d=new Date();
  const p=n=>String(n).padStart(2,'0');
  return `${d.getFullYear()}${p(d.getMonth()+1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

async function analyze(){
  const tk=getTicker(); if(!tk){ toast('Masukkan kode saham dulu.'); return; }
  setTicker(tk);
  LAST_ADVISOR = null; // analisa baru → advisor lama tidak relevan
  $('#aout').innerHTML=`<section class="glass-panel"><div class="flex"><span class="spin"></span>
    <span class="dim">Menjalankan funnel untuk <b>${esc(tk)}</b>…</span></div>
    <div class="skel" style="margin-top:1rem"></div><div class="skel" style="margin-top:.5rem;width:70%"></div></section>`;
  let d; try{ d=await api('/api/analyze/'+encodeURIComponent(tk)); }catch(e){ $('#aout').innerHTML='<section class="glass-panel"><div class="empty">Gagal memuat.</div></section>'; return; }
  if(d && d.detail){ $('#aout').innerHTML=`<section class="glass-panel"><div class="empty">${esc(d.detail)}</div></section>`; return; }
  LAST_ANALYZE = d;
  if(d.input_mode==='manual' || d.in_funnel_universe===false) saveManualTicker(d.ticker||tk);
  const rec=d.rekomendasi, sh=d.sharia, f=d.fundamental, c=d.canslim, t=d.technical, b=d.bandarmologi;
  const bk=bucket(rec.css);
  const manualMode = d.input_mode==='manual' || d.in_funnel_universe===false || (sh&&sh.des_status==='outside_curated');
  const syariahLabel = sh.compliant ? (manualMode ? '✓ Syariah*' : '✓ Syariah') : 'Non-Syariah';
  const syariahTip = manualMode
    ? 'Di luar universe funnel terkurasi — verifikasi DES/ISSI mandiri'
    : (sh.compliant ? 'Kompatibel DES' : 'Non-DES');

  let h=`<div id="ai-slot"></div>`;
  h+=`<section class="glass-panel decision-panel" style="border: 2px solid var(--brand); padding: 1.7rem; box-shadow: 0 8px 32px rgba(59, 130, 246, 0.15);"><div class="between" style="align-items:flex-start">
    <div style="flex: 1; padding-right: 1.5rem;">
      <div class="flex" style="gap: .7rem; align-items: center; flex-wrap:wrap;">
        <div style="font-size: 2.1rem; font-weight: 800; tracking: -0.5px;">${esc(d.ticker)}</div>
        <span class="badge ${sh.compliant?'buy':'sell'}" style="font-size: .85rem; padding: .3rem .75rem; cursor: pointer;" onclick="explainMetric('${esc(d.ticker)}', 'Kepatuhan Syariah', '${sh.compliant?'Lolos':'Gagal'}', '${esc(syariahTip)}')">${syariahLabel}</span>
        ${manualMode?`<span class="badge warning" style="font-size:.75rem;padding:.25rem .6rem" title="Analisa on-demand di luar ~100 saham funnel">✎ Manual</span>`:`<span class="badge na" style="font-size:.75rem;padding:.25rem .6rem" title="Termasuk universe funnel">Funnel</span>`}
        <button class="btn secondary" style="font-size:.75rem;padding:.25rem .55rem;margin-left:auto" onclick="downloadAnalyzeMd()" title="Unduh Markdown Analisa">📥 MD Analisa</button>
      </div>
      <div class="dim" style="margin-top:.2rem; font-size: .95rem; font-weight: 500;">${esc(d.name)||''} · ${esc(d.sector)||''}</div>
      ${manualMode?`<div class="mut" style="font-size:.78rem;margin-top:.45rem;padding:.45rem .65rem;border-radius:8px;background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.25);line-height:1.45">✎ <b>Input manual</b> — di luar universe funnel terkurasi. Fundamental mungkin dari yfinance (kurang lengkap). Verifikasi keanggotaan DES/ISSI sebelum bertransaksi.</div>`:''}
      ${(d.data_notes&&d.data_notes.length)?`<div class="mut" style="font-size:.75rem;margin-top:.4rem;color:var(--mute)">📎 ${d.data_notes.map(esc).join(' · ')}</div>`:''}
      <div class="mut" style="font-size:.74rem;margin-top:.6rem;display:flex;gap:.8rem;flex-wrap:wrap;align-items:center">
        <span>🌐 <b>Teknikal & Harga:</b> Yahoo Finance (Intraday ~10-15m)</span>
        <span>📊 <b>Fundamental:</b> ${manualMode?'yfinance / data tersedia':'Laporan Keuangan Aktual (DES Terkurasi)'}</span>
        <span>⏱️ <b>Cache TTL:</b> 10 Menit</span>
      </div>
      <div style="margin-top: 1.1rem;">
        <span class="badge ${rec.css||'na'}" style="font-size: 1.05rem; padding: .45rem 1.1rem; border-radius: 10px; font-weight: 800; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);">
          📢 Rekomendasi: ${esc(rec.final_signal||rec.aksi)}
        </span>
      </div>
      <ul style="margin: 1.1rem 0 0; padding-left: 1.25rem; font-size: 1.02rem; line-height: 1.8; color: var(--text);">
        ${rec.alasan.map(a => {
          const idx = a.indexOf(':');
          if (idx !== -1) {
            const label = a.substring(0, idx);
            const rest = a.substring(idx + 1);
            return `<li style="margin-bottom: .45rem;"><b>${esc(label)}</b>:${esc(rest)}</li>`;
          }
          return `<li style="margin-bottom: .45rem;">${esc(a)}</li>`;
        }).join('')}
      </ul>
    </div>
    <div style="text-align:center; flex-shrink: 0; display: flex; flex-direction: column; justify-content: center; align-items: center;">
      ${ring(rec.skor,'Skor Funnel')}
    </div>
  </div></section>`;

  // Skor dua lapis (Hard Gate → Quality → Timing → Regime → Final)
  const sc=rec.scoring;
  if(sc && sc.model==='layered'){
    const reg=sc.regime||{};
    const regCls=reg.regime==='BULLISH'?'buy':reg.regime==='BEARISH'?'sell':'warning';
    const elig=sc.eligible_for_buy;
    const kep=(sc.keputusan||'').toUpperCase();
    const kepCls=kep==='STRONG BUY'?'buy':kep==='WATCHLIST'?'warning':'sell';
    const gates=((sc.gates&&sc.gates.gates)||[]);
    const comps=sc.components||{};
    const gateHtml=gates.map(g=>`<span class="badge ${g.passed?'buy':'sell'}" style="font-size:.68rem;padding:2px 7px" title="${esc(g.detail||'')}">${g.passed?'✓':'✕'} ${esc(g.nama||g.id||'')}</span>`).join(' ');
    const compRows=Object.keys(comps).map(k=>{
      const c=comps[k];
      const pct=Math.round((c.nilai||0)*100);
      const w=Math.round((c.bobot||0)*100);
      return `<div style="display:flex;align-items:center;gap:.5rem;margin-top:.35rem;font-size:.78rem">
        <span style="width:7.2rem;text-transform:capitalize">${esc(k)}</span>
        <div style="flex:1;height:7px;background:var(--line);border-radius:4px;overflow:hidden"><div style="width:${pct}%;height:100%;background:var(--brand)"></div></div>
        <span class="mut" style="width:5.5rem;text-align:right">${c.skor_100??pct} · ${w}% → ${c.kontribusi??'—'}</span>
      </div>`;
    }).join('');
    const maNote = reg.pct_ma20_vs_ma60!=null
      ? `(MA20 vs MA60 ${reg.pct_ma20_vs_ma60}%)`
      : (reg.pct_vs_sma200!=null?`(${reg.pct_vs_sma200}% vs SMA200)`:'');
    h+=`<section class="glass-panel" style="margin-top:1rem">
      <div class="between" style="margin-bottom:.7rem;align-items:flex-start;flex-wrap:wrap;gap:.5rem">
        <h3 class="sec" style="margin:0">🧮 Skor Rekomendasi</h3>
        <div class="flex" style="gap:.35rem;flex-wrap:wrap">
          <span class="badge ${kepCls}" style="font-size:.7rem">${esc(sc.keputusan||'—')} · Final ${sc.final_score??sc.skor??'—'}</span>
          <span class="badge ${elig?'buy':'sell'}" style="font-size:.7rem">${elig?'Eligible BELI':'Tidak eligible'}</span>
          <span class="badge ${regCls}" style="font-size:.7rem">${esc(reg.regime||'—')} · ×${sc.size_mult??1}</span>
          <span class="badge na" style="font-size:.7rem">Q ${sc.quality_score??'—'} · T ${sc.timing_score??'—'}${sc.timing_layak_entry?' ✓':' <65'}</span>
        </div>
      </div>
      <div class="mut" style="font-size:.78rem;margin-bottom:.55rem">${esc(reg.label||'')} ${maNote}</div>
      <div class="flex" style="gap:.35rem;flex-wrap:wrap;margin-bottom:.7rem">${gateHtml||'<span class="mut">—</span>'}</div>
      ${compRows}
      <div class="mut" style="font-size:.7rem;margin-top:.7rem;line-height:1.5">Hard gate: DES/ISSI → spread≤2% &amp; vol median 5d ≥Rp5jt → IHSG bukan ekstrem (MA20&lt;MA60 by &gt;5%). Quality = Fund×0.3 + Tech×0.2 + Bandar×0.15 + Liq×0.15 + IHSG×0.15 + Risk×0.1. Final = Quality×Multiplier (+ Timing Bonus 0). ≥75 STRONG BUY · 55–74 WATCHLIST · &lt;55 SKIP. Timing layak entry ≥65.</div>
    </section>`;
  }

  h+=shariaCard(sh);

  h+=`<section class="glass-panel"><div class="between" style="margin-bottom:.8rem">
    <h3 class="sec" style="margin:0">📈 Grafik Harga & Indikator</h3><div id="px-head" class="dim"></div></div>
    <div class="chartwrap"><div id="chart"></div><div id="stoch"></div>
      <div class="legend"><span><i style="background:#3b82f6"></i>SMA20</span><span><i style="background:#eab308"></i>SMA50</span>
        <span><i style="background:#a78bfa"></i>SMA200</span><span><i style="background:var(--buy)"></i>Support/Resistance</span>
        <span><i style="background:var(--brand-2)"></i>%K/%D stochastic (OB80/OS20)</span></div></div>
    <div id="sig-box"></div></section>`;

  h+=`<div class="grid g-2">`;
  h+=`<section class="glass-panel"><div class="between" style="margin-bottom:.6rem"><h3 class="sec" style="margin:0">💎 6 Magic Number <span class="badge ${f.source==='master_data'?'buy':'na'}" style="font-size:.58rem;text-transform:none">${f.source==='master_data'?'data terkurasi':'yfinance'}</span></h3>
    ${ringScore(f.magic_score,6,f.verdict)}</div>${f.checks.map(crow).join('')}
    <div class="crow" style="margin-top:.2rem"><div><div class="nm">${esc(f.bonus_dividend.kriteria)}</div><div class="tg">${esc(f.bonus_dividend.target)}</div></div>
      <div class="flex"><span class="vl">${esc(f.bonus_dividend.nilai)}</span>${pill(f.bonus_dividend.lolos, null, f.bonus_dividend.kriteria, f.bonus_dividend.nilai)}</div></div></section>`;
  let lt=''; for(const k in c.letters){ const L=c.letters[k];
    lt+=`<div class="lt ${L.lolos===true?'pass':L.lolos===false?'fail':''}" title="${esc(L.kriteria)}: ${esc(L.nilai)}"><b>${k}</b><small>${L.lolos===true?'✓':L.lolos===false?'✕':'·'}</small></div>`; }
  h+=`<section class="glass-panel"><div class="between" style="margin-bottom:.6rem"><h3 class="sec" style="margin:0">⚡ CAN SLIM</h3>
    ${ringScore(c.canslim_score,7,c.verdict)}</div><div class="letters">${lt}</div>
    <div style="margin-top:.9rem">${cslimRows(c.letters)}</div></section></div>`;

  if(t.ok){ const z=t.stochastic.zona;
    const adxVal = t.adx ? (t.adx.value != null ? t.adx.value : '—') : '—';
    const adxStr = t.adx ? t.adx.strength : '—';
    const adxCls = t.adx ? t.adx.class : '';
    const atrVal = t.atr ? (t.atr.value != null ? fmt(t.atr.value) : '—') : '—';
    const atrPct = t.atr ? (t.atr.pct != null ? t.atr.pct + '%' : '—') : '—';
    const atrSl = t.atr ? (t.atr.sl_2atr != null ? 'SL: ' + fmt(t.atr.sl_2atr) : '—') : '—';
    const atrTp = t.atr ? (t.atr.tp_4atr != null ? 'TP: ' + fmt(t.atr.tp_4atr) : '—') : '—';

    h+=`<section class="glass-panel"><h3 class="sec">🎯 Ringkasan Teknikal — <span class="dim" style="text-transform:none">${esc(t.bias)}</span></h3>
      <div class="grid g-auto">
        ${stat('Harga',fmt(t.price))}${stat('Tren',t.trend,t.trend==='UPTREND'?'up':t.trend==='DOWNTREND'?'down':'')}
        ${stat('Stochastic',t.stochastic.k!=null?('%K '+t.stochastic.k):'—',z==='oversold'?'up':z==='overbought'?'down':'',t.stochastic.sinyal)}
        ${stat('vs SMA200',t.sma.price_vs_sma200,t.sma.price_vs_sma200==='di atas'?'up':'down','SMA200 '+fmt(t.sma.sma200))}
        ${stat('ADX Trend Strength',adxVal,adxCls,adxStr)}
        ${stat('ATR Volatility',atrVal,'',`vol: ${atrPct} · ${atrSl} · ${atrTp}`)}
        ${b ? stat('Bandarmologi (Smart Money)', b.sentiment, b.sentiment.includes('AKUMULASI') ? 'up' : b.sentiment.includes('DISTRIBUSI') ? 'down' : '', `skor: ${b.score}/100 · ${b.note}`) : ''}
        ${t.volume_profile ? stat('Volume Profile (POC)', fmt(t.volume_profile.poc), '', `VAL: ${fmt(t.volume_profile.val)} · VAH: ${fmt(t.volume_profile.vah)}`, 'Point of Control (POC): tingkat harga dengan akumulasi volume transaksi terbesar dalam 60 hari bursa terakhir. VAL & VAH mencakup 70% Value Area (luas transaksi bernilai tinggi).') : ''}
        ${t.volatility_insight_pro ? stat('Volatility Insight Pro', `${t.volatility_insight_pro.rating} / 5.0`, t.volatility_insight_pro.rating >= 4.0 ? 'up' : t.volatility_insight_pro.rating < 2.5 ? 'down' : 'hold', t.volatility_insight_pro.conviction, `Rating multi-faktor kuantitatif (1 s/d 5):\n${t.volatility_insight_pro.details.join('\n')}`) : ''}
        ${stat('Support',fmt(t.support))}${stat('Resistance',fmt(t.resistance))}</div>
      ${srZones(t)}
      ${fiboPanel(t)}
      ${t.candlestick.length?'<div style="margin-top:.9rem">'+t.candlestick.map(p=>`<span class="badge na" style="margin-right:.4rem">${esc(p)}</span>`).join('')+'</div>':''}</section>`;
  } else h+=`<section class="glass-panel"><div class="empty">${esc(t.error||'data teknikal tidak cukup')}</div></section>`;

  if(d.jalur7 && d.jalur7.ok) h+=jalur7Card(d.jalur7);

  $('#aout').innerHTML=h;
  if(t.ok && t.entry_signals.length){
    $('#sig-box').innerHTML='<div style="margin-top:.9rem"><div class="dim" style="font-size:.74rem;font-weight:700;margin-bottom:.2rem">SINYAL ENTRY TERDETEKSI</div>'+
      t.entry_signals.map(s=>`<div class="sig"><span class="code">${s.kode}</span><div><div style="font-weight:600">${esc(s.nama)}</div>
        <div class="dsc">${esc(s.detail)} ${s.volume_konfirmasi?'· <span style="color:var(--buy)">volume kuat</span>':''}</div></div></div>`).join('')+'</div>';
  } else if(t.ok) $('#sig-box').innerHTML='<p class="sub" style="margin-top:.8rem">Belum ada sinyal entry pada candle terakhir.</p>';
  renderChart(tk,t);
  loadDividend(tk);
}
async function loadDividend(tk){
  try{ const p=await api('/api/dividend/'+tk); const u=p.upcoming||{};
    const reg = p.regular?`<span class="badge buy" style="font-size:.6rem" title="${p.frequency||''} · ${p.pay_streak||p.years_paid} thn beruntun">rutin ${p.pay_streak||p.years_paid} thn</span>`:'<span class="badge na" style="font-size:.6rem">tidak rutin</span>';
    let up='';
    if(u.expected){ const soon=(u.days_until!=null&&u.days_until<=21);
      up=`<div style="margin-top:.5rem;padding:.5rem .7rem;border-radius:10px;background:${soon?'rgba(34,197,94,.12)':'rgba(255,255,255,.04)'};border:1px solid var(--line)">
        💵 <b>Dividen mendatang</b>: ex-date <b>${u.ex_date}</b>${u.days_until!=null?` (${u.days_until} hari lagi)`:''} · ~Rp ${u.amount?Number(u.amount).toFixed(0):'?'}/lembar${u.event_yield_pct?` ≈ <b>${u.event_yield_pct}%</b>`:''}
        <div class="mut" style="font-size:.7rem">sumber: ${esc(u.source||'-')}${soon?' · <b style="color:var(--buy)">SELL sebaiknya ditunda demi dividen (bila bukan cut-loss)</b>':''}</div></div>`;
    } else up='<div class="mut" style="margin-top:.4rem;font-size:.78rem">Tidak ada perkiraan dividen dekat.</div>';
    const isManual = u.source==='kalender manual';
    const form=`<details style="margin-top:.5rem"><summary class="sub" style="cursor:pointer;font-size:.78rem">✏️ Set / ubah cum-date &amp; dividen manual (paling presisi)</summary>
      <div class="row" style="margin-top:.5rem">
        <label class="fld"><span class="l">Ex-date / cum-date</span><input id="div-ex" type="date" value="${isManual&&u.ex_date?u.ex_date:''}"></label>
        <label class="fld"><span class="l">Dividen Rp/lembar</span><input id="div-amt" type="number" value="${isManual&&u.amount?u.amount:''}"></label>
        <button class="btn primary" onclick="saveDividend('${tk}')">💾 Simpan</button>
        ${isManual?`<button class="btn ghost" onclick="delDividend('${tk}')">🗑 Hapus</button>`:''}
      </div></details>`;
    const card=`<section class="glass-panel" style="margin-top:1.2rem"><h3 class="sec">💵 Dividen</h3>
      <div class="flex" style="gap:.7rem;flex-wrap:wrap">${reg} <span class="sub">yield ~${p.dividend_yield??'-'}% · ${p.n_payments} kali bayar · terakhir ex ${p.last_ex||'-'}</span></div>${up}
      ${form}
      <p class="sub" style="margin-top:.4rem;font-size:.7rem">Data yfinance (setara TradingView). Saat RUPS diumumkan, isi cum-date persis di atas agar keputusan tunda-SELL 100% akurat.</p></section>`;
    $('#aout').insertAdjacentHTML('beforeend', card);
  }catch(e){}
}
function _removeDividendCard(){ const s=[...document.querySelectorAll('#aout section')].find(x=>/💵\s*Dividen/.test(x.textContent.slice(0,40))); if(s) s.remove(); }
async function saveDividend(tk){
  const ex=$('#div-ex').value, amt=+$('#div-amt').value;
  if(!ex||!amt){ toast('Isi cum-date & nominal dividen dulu.'); return; }
  const d=await post('/api/dividend/calendar',{ticker:tk,ex_date:ex,amount:amt});
  if(d&&d.detail){ toast(d.detail); return; }
  toast('Cum-date '+tk+' disimpan.'); _removeDividendCard(); loadDividend(tk);
}
async function delDividend(tk){
  if(!confirm('Hapus kalender dividen manual '+tk+'?')) return;
  await fetch('/api/dividend/calendar/'+tk,{method:'DELETE'});
  toast('Kalender dividen '+tk+' dihapus.'); _removeDividendCard(); loadDividend(tk);
}
function shariaCard(sh){
  const dv=(sh.dsn_mui||{}).verdict||'-';
  const dvc=dv==='HALAL'?'buy':(dv==='HARAM'||dv==='NON-COMPLIANT')?'sell':'warning';
  const aa=(sh.aaoifi||{}).summary||'-';
  const aac=aa==='PASS'?'buy':aa==='FAIL'?'sell':'warning';
  const rows=(sh.checks||[]).map(c=>`<div class="crow"><div style="min-width:0"><div class="nm">${esc(c.kriteria)}</div><div class="tg">${esc(c.acuan||'')}</div></div>
    <div class="flex"><span class="vl">${esc(c.nilai)}</span>${pill(c.lolos, null, c.kriteria, c.nilai)}</div></div>`).join('');
  return `<section class="glass-panel"><div class="between" style="margin-bottom:.6rem">
    <h3 class="sec" style="margin:0">☪ Kepatuhan Syariah</h3>
    <div class="flex"><span class="badge ${dvc}" style="cursor: pointer;" onclick="explainMetric(document.getElementById('tk').value.trim().toUpperCase(), 'Kepatuhan Syariah (DSN-MUI)', '${esc(dv)}', '${esc(dv)}')">DSN-MUI: ${esc(dv)}</span><span class="badge ${aac}" style="cursor: pointer;" onclick="explainMetric(document.getElementById('tk').value.trim().toUpperCase(), 'Kepatuhan Syariah (AAOIFI)', '${esc(aa)}', '${esc(aa)}')">AAOIFI: ${esc(aa)}</span></div></div>
    ${rows}<p class="sub">${esc(sh.catatan||'')}</p></section>`;
}
function crow(c){ return `<div class="crow"><div><div class="nm">${esc(c.kriteria)}</div><div class="tg">target ${esc(c.target)}</div></div>
  <div class="flex"><span class="vl">${esc(c.nilai)}</span>${pill(c.lolos, null, c.kriteria, c.nilai)}</div></div>`; }
function cslimRows(L){ return Object.keys(L).map(k=>`<div class="crow"><div><div class="nm"><b style="color:var(--brand-2)">${k}</b> ${esc(L[k].kriteria)}</div>
  <div class="tg">${esc(L[k].nilai)}</div></div>${pill(L[k].lolos, null, L[k].kriteria, L[k].nilai)}</div>`).join(''); }
function stat(lbl,val,cls,sub,tip){ return `<div class="stat"${tip?` title="${esc(tip)}"`:''} style="${tip?'cursor:help;':''}"><div class="lbl">${lbl}</div><div class="big num ${cls||''}" style="font-size:1.15rem">${val}</div>${sub?`<div class="sub num">${esc(sub)}</div>`:''}</div>`; }
function srZones(t){
  const lv=(t.sr_levels||[]);
  if(!lv.length && !t.sr_note) return '';
  const chips=lv.map(z=>{
    const isRes=z.jenis==='resistance', cls=isRes?'sell':'buy';
    const star='●'.repeat(Math.min(z.kekuatan,4));
    return `<span class="sr-chip ${cls}" title="${isRes?'Resistance':'Support'} · ${z.kekuatan} sentuhan · ${z.jarak_pct>0?'+':''}${z.jarak_pct}% dari harga">
      <b>${isRes?'R':'S'}</b> ${fmt(z.level)} <i class="sr-str">${star}</i> <em class="num">${z.jarak_pct>0?'+':''}${z.jarak_pct}%</em></span>`;
  }).join('');
  return `<div class="sr-box">
    <div class="sr-title">📏 Zona Support &amp; Resistance <span class="dim" style="font-weight:600;text-transform:none">(● = kekuatan / jumlah sentuhan)</span></div>
    ${chips?`<div class="sr-chips">${chips}</div>`:''}
    ${t.sr_note?`<p class="sub" style="margin:.6rem 0 0">${esc(t.sr_note)}</p>`:''}</div>`;
}
function fiboPanel(t) {
  if (!t.fibonacci) return '';
  const f = t.fibonacci;
  const levels = f.levels || {};
  const keys = ['level_23.6', 'level_38.2', 'level_50.0', 'level_61.8', 'level_78.6'];
  const chips = keys.map(k => {
    const lvl = levels[k];
    if (lvl == null) return '';
    const label = k.replace('level_', '') + '%';
    const isGolden = label === '61.8%';
    const cls = isGolden ? 'buy' : 'na';
    const style = isGolden ? 'font-weight:800;border:1px dashed var(--buy)' : '';
    return `<span class="sr-chip ${cls}" style="${style}" title="Level Fibonacci Retracement ${label}"><b>Fibo ${label}</b> ${fmt(lvl)}</span>`;
  }).join('');

  let nextCycle = null;
  if (f.time_cycles) {
    for (const cyc of f.time_cycles) {
      if (cyc.days_left != null && cyc.days_left >= 0) {
        if (!nextCycle || cyc.days_left < nextCycle.days_left) nextCycle = cyc;
      }
    }
  }

  let timeHtml = '';
  if (nextCycle) {
    const daysStr = nextCycle.days_left === 0 ? 'hari ini' : `${nextCycle.days_left} hari bursa lagi`;
    timeHtml = `<div style="margin-top:.5rem;font-size:.78rem" class="dim">⏱️ <b>Astronacci Time Cycle:</b> Potensi pembalikan arah berikutnya (Siklus Fibo ${nextCycle.cycle}) diperkirakan pada <b>${nextCycle.date}</b> (${daysStr}).</div>`;
  } else if (f.time_cycles && f.time_cycles.length) {
    const lastC = f.time_cycles[f.time_cycles.length - 1];
    timeHtml = `<div style="margin-top:.5rem;font-size:.78rem" class="dim">⏱️ <b>Astronacci Time Cycle:</b> Siklus Fibo ${lastC.cycle} pada ${lastC.date}.</div>`;
  }

  return `<div class="sr-box" style="margin-top:.8rem;border-top:1px solid var(--line);padding-top:.8rem">
    <div class="sr-title">🎯 Proyeksi Fibonacci &amp; Waktu (Metode Astronacci Syariah)</div>
    <div class="sr-chips" style="margin-top:.5rem">${chips}</div>
    ${f.closest_level_note ? `<p class="sub" style="margin:.4rem 0 0;font-weight:600;color:var(--buy)">${esc(f.closest_level_note)}</p>` : ''}
    ${timeHtml}</div>`;
}
function jalur7Card(j){
  const rows=Object.values(j.signals).map(s=>`<div class="crow"><div style="min-width:0">
    <div class="nm">${s.pass?'✅':'❌'} ${esc(s.nama)} <span class="badge ${s.pass?'buy':'na'}" style="font-size:.6rem">${esc(s.label)}</span></div>
    <div class="tg">${esc(s.reason)}</div></div></div>`).join('');
  const kf=Object.entries(j.konfirmasi).map(([k,v])=>`<span class="badge ${v.ok?'buy':'na'}" style="margin-right:.4rem">${k}: ${esc(v.detail)}</span>`).join('');
  const c=j.score>=3?'var(--buy)':j.score===2?'var(--hold)':'var(--sell)';
  return `<section class="glass-panel"><div class="between" style="margin-bottom:.6rem">
    <h3 class="sec" style="margin:0">⚔️ Jalur 7% — Struktur Teknikal</h3>
    <div class="ring" style="--p:${j.score/4*100};--c:${c}"><div class="v"><b>${j.score}<small style="font-size:.8rem;color:var(--mute)">/4</small></b><span>sinyal</span></div></div></div>
    <div style="margin-bottom:.5rem"><span class="badge ${j.score>=3?'buy':j.score===2?'hold':'sell'}">${esc(j.verdict)}</span></div>
    ${rows}
    <div style="margin-top:.8rem"><div class="tg" style="margin-bottom:.3rem">Konfirmasi berlapis (Tren + Momentum + Volume): ${j.konfirmasi_count}/3</div>${kf}</div>
    <p class="sub">${esc(j.catatan)}</p></section>`;
}

/* chart */
let _charts=[];
async function renderChart(tk,tech){
  _charts.forEach(c=>{try{c.remove()}catch(e){}}); _charts=[];
  let cd; try{ cd=await api('/api/chart/'+tk); }catch(e){ return; }
  if(!cd.ok||!cd.candles.length){ $('#chart').innerHTML='<div class="empty">grafik tidak tersedia</div>'; return; }
  const LC=window.LightweightCharts, dark=document.documentElement.getAttribute('data-theme')!=='light';
  const txt=dark?'#94a3b8':'#475569', grid=dark?'rgba(255,255,255,.05)':'rgba(15,23,42,.06)', bd=dark?'#334155':'#cbd5e1';
  const base={layout:{background:{color:'transparent'},textColor:txt,fontFamily:'Outfit'},
    grid:{vertLines:{color:grid},horzLines:{color:grid}},rightPriceScale:{borderColor:bd},timeScale:{borderColor:bd},crosshair:{mode:LC.CrosshairMode.Normal}};
  const main=LC.createChart($('#chart'),{...base,width:$('#chart').clientWidth,height:380});
  const candle=main.addCandlestickSeries({upColor:'#10b981',downColor:'#ef4444',borderVisible:false,wickUpColor:'#10b981',wickDownColor:'#ef4444'});
  candle.setData(cd.candles);
  const vol=main.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'vol'}); main.priceScale('vol').applyOptions({scaleMargins:{top:.84,bottom:0}}); vol.setData(cd.volume);
  const mk=(data,color)=>{ if(data&&data.length){ const s=main.addLineSeries({color,lineWidth:2,priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false}); s.setData(data);} };
  mk(cd.sma20,'#3b82f6'); mk(cd.sma50,'#eab308'); mk(cd.sma200,'#a78bfa');
  const srLevels=(cd.sr_levels||[]);
  if(srLevels.length){
    srLevels.forEach(z=>{ const isRes=z.jenis==='resistance';
      candle.createPriceLine({price:z.level,color:isRes?'rgba(239,68,68,.55)':'rgba(16,185,129,.55)',
        lineWidth:Math.min(z.kekuatan,3),lineStyle:2,axisLabelVisible:true,
        title:(isRes?'R':'S')+(z.kekuatan>1?'×'+z.kekuatan:'')});
    });
  } else {
    if(cd.support) candle.createPriceLine({price:cd.support,color:'#10b981',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'S'});
    if(cd.resistance) candle.createPriceLine({price:cd.resistance,color:'#ef4444',lineWidth:1,lineStyle:2,axisLabelVisible:true,title:'R'});
  }
  // Garis Fundamental: Harga Wajar (Graham Number) & Nilai Buku (BVPS)
  if(cd.graham_number){
    candle.createPriceLine({price:cd.graham_number,color:'#ec4899',lineWidth:2,lineStyle:1,axisLabelVisible:true,title:'Harga Wajar (Graham)'});
  }
  if(cd.bvps){
    candle.createPriceLine({price:cd.bvps,color:'#06b6d4',lineWidth:2,lineStyle:3,axisLabelVisible:true,title:'Nilai Buku (BVPS)'});
  }
  if(tech&&tech.entry_signals&&tech.entry_signals.length){ const last=cd.candles[cd.candles.length-1].time;
    candle.setMarkers(tech.entry_signals.slice(0,4).map(s=>({time:last,position:'belowBar',color:'#3b82f6',shape:'arrowUp',text:s.kode}))); }
  const last=cd.candles.at(-1), prev=cd.candles.at(-2)||last, ch=((last.close-prev.close)/prev.close*100);
  $('#px-head').innerHTML=`<span class="num" style="font-size:1.1rem;font-weight:800;color:var(--text)">${fmt(last.close)}</span>
    <span class="num" style="color:${ch>=0?'var(--buy)':'var(--sell)'};font-weight:700"> ${ch>=0?'▲':'▼'}${Math.abs(ch).toFixed(2)}%</span>`;
  const st=LC.createChart($('#stoch'),{...base,width:$('#stoch').clientWidth,height:110,rightPriceScale:{borderColor:bd,scaleMargins:{top:.1,bottom:.1}},timeScale:{visible:false,borderColor:bd}});
  const kS=st.addLineSeries({color:'#3b82f6',lineWidth:2,priceLineVisible:false}); const dS=st.addLineSeries({color:'#eab308',lineWidth:1,priceLineVisible:false,lastValueVisible:false});
  kS.setData(cd.stoch_k); dS.setData(cd.stoch_d);
  kS.createPriceLine({price:80,color:'rgba(239,68,68,.4)',lineWidth:1,lineStyle:1,axisLabelVisible:false});
  kS.createPriceLine({price:20,color:'rgba(16,185,129,.4)',lineWidth:1,lineStyle:1,axisLabelVisible:false});
  let lock=false; const sync=(a,b)=>a.timeScale().subscribeVisibleLogicalRangeChange(r=>{if(lock||!r)return;lock=true;b.timeScale().setVisibleLogicalRange(r);lock=false;});
  sync(main,st); sync(st,main); main.timeScale().fitContent(); st.timeScale().fitContent(); _charts=[main,st];
  window.addEventListener('resize',()=>{main.applyOptions({width:$('#chart').clientWidth});st.applyOptions({width:$('#stoch').clientWidth});});
}

/* AI advisor */
async function loadEngines(){
  try{ const s=await api('/api/advisor/status'); const e=s.engines; const sel=$('#adv-engine');
    const opt=(v,l)=>`<option value="${v}">${l}</option>`;
    let html=opt('auto','⚙ Auto');
    if(e.gemini && e.gemini.tersedia) html+=opt('gemini','✦ Gemini (gratis)');
    if(e.deepseek && e.deepseek.tersedia) html+=opt('deepseek','◈ DeepSeek');
    html+=opt('lokal','⚡ Lokal (instan)');
    sel.innerHTML=html; sel.value=s.default||'lokal';
    const notes=[];
    if(e.gemini && e.gemini.tersedia) notes.push(`Gemini: <b>${esc(e.gemini.model)}</b>`);
    else notes.push('Gemini: <b>nonaktif</b> (set <code>GEMINI_API_KEY</code>)');
    if(e.deepseek && e.deepseek.tersedia) notes.push(`DeepSeek: <b>${esc(e.deepseek.model)}</b>`);
    else notes.push('DeepSeek: <b>nonaktif</b> (set <code>DEEPSEEK_API_KEY</code>)');
    notes.push('Lokal: selalu siap');
    $('#adv-hint').innerHTML = `Engine: ${notes.join(' · ')}`;
    
    const strategyLed = document.getElementById('led-agent-strategy');
    if (strategyLed) {
      const on = (e.gemini && e.gemini.tersedia) || (e.deepseek && e.deepseek.tersedia);
      strategyLed.style.background = on ? '#00d26a' : '#eab308';
      strategyLed.style.boxShadow = on ? '0 0 8px #00d26a' : '0 0 8px #eab308';
    }
  }catch(e){}
  
  // Update Telegram Agent LED
  try {
    const t = await api('/api/telegram/status');
    const telegramLed = document.getElementById('led-agent-telegram');
    if (telegramLed) {
      if (t.configured && t.enabled) {
        telegramLed.style.background = '#00d26a';
        telegramLed.style.boxShadow = '0 0 8px #00d26a';
      } else {
        telegramLed.style.background = '#666';
        telegramLed.style.boxShadow = 'none';
      }
    }
  }catch(e){}
}
async function advisor(){
  const tk=getTicker(); if(!tk){ toast('Masukkan kode saham dulu.'); return; }
  setTicker(tk);
  if(!$('#aout').innerHTML.trim()) await analyze();
  const eng=$('#adv-engine').value||'auto';
  const slot=aiSlot();
  const wait = (eng==='gemini' || (eng==='auto' && !$('#adv-engine').querySelector('option[value=deepseek]')))
    ? `Gemini sedang menganalisa ${esc(tk)}… <span class="dim">(±5–10 dtk)</span>`
    : eng==='deepseek'
    ? `DeepSeek sedang menganalisa ${esc(tk)}… <span class="dim">(±5–15 dtk)</span>`
    : eng==='auto'
    ? `Advisor AI sedang menganalisa ${esc(tk)}…`
    : `Menyusun analisa ${esc(tk)}…`;
  slot.innerHTML=`<section class="glass-panel ai-box"><h3 class="sec">✦ Advisor</h3><div class="flex"><span class="spin"></span><span>${wait}</span></div></section>`;
  try{ const d=await api('/api/advisor/'+encodeURIComponent(tk)+'?engine='+eng);
    if(d.enabled===false){ slot.innerHTML=`<section class="glass-panel ai-box"><h3 class="sec">✦ Advisor</h3><p class="dim">${esc(d.message)}</p></section>`; return; }
    if(d.error){ slot.innerHTML=`<section class="glass-panel ai-box"><h3 class="sec">✦ Advisor</h3><p style="color:var(--sell)">${esc(d.error)}</p></section>`; return; }
    LAST_ADVISOR = d;
    if(!CURRENT_TICKERS.includes(tk)) saveManualTicker(tk);
    let u='';
    if(d.usage){ const parts=[]; if(d.usage.output_tokens)parts.push(d.usage.output_tokens+' tok');
      if(d.usage.durasi_detik)parts.push(d.usage.durasi_detik+'s'); if(d.usage.cache_read_input_tokens)parts.push('cache hit');
      if(d.usage.input_tokens)parts.push(d.usage.input_tokens+' in');
      if(parts.length)u=' · '+parts.join(' · '); }
    const fb = d.fallback_dari ? ` <span class="mut">(fallback dari ${esc(d.fallback_dari)})</span>` : '';
    slot.innerHTML=`<section class="glass-panel ai-box"><div class="between" style="align-items:center;gap:.5rem;margin-bottom:.35rem"><h3 class="sec" style="margin:0">✦ Advisor <span class="mut" style="font-weight:600;text-transform:none">${esc(d.model||'')}${u}</span>${fb}</h3>
      <button class="btn secondary" style="font-size:.75rem;padding:.25rem .55rem" onclick="downloadAdvisorMd()" title="Unduh Markdown Advisor">📥 MD</button></div>${aiVerdict(d.verdict)}<div class="ai-text">${mdb(d.analisa)}</div></section>`;
  }catch(e){ slot.innerHTML=`<section class="glass-panel ai-box"><p class="dim">Gagal: ${e}</p></section>`; }
}
function aiVerdict(v){
  if(!v) return '';
  const rec=(v.rekomendasi_claude||v.rekomendasi||'').toString().toUpperCase();
  const cls = /STRONG BUY|^BUY|ACCUMULATE/.test(rec)?'buy' : /AVOID|SELL/.test(rec)?'sell' : 'hold';
  const adj=v.penyesuaian_conviction;
  const adjStr = (adj!=null && Number(adj)!==0) ? `${Number(adj)>0?'+':''}${adj} conviction vs mesin` : 'sejalan dgn mesin';
  const vs = (v.vs_mesin||'').toString().replace(/_/g,' ').toLowerCase();
  const num = x => (x!=null && x!=='' && !isNaN(Number(x))) ? Number(x).toLocaleString('id-ID') : null;
  const plan=[];
  if(num(v.entry_ideal)) plan.push(`Entry <b>${num(v.entry_ideal)}</b>`);
  if(num(v.stop_loss)) plan.push(`SL <b class="loss">${num(v.stop_loss)}</b>`);
  if(num(v.target_harga)) plan.push(`TP <b class="gain">${num(v.target_harga)}</b>`);
  if(v.rrr) plan.push(`RRR <b>${esc(v.rrr)}</b>`);
  const planHtml = plan.length ? `<div class="ai-verdict-plan">📋 Rencana: ${plan.join(' · ')}</div>` : '';
  const horizon = v.horizon ? `<span>Horizon: <b>${esc(v.horizon)}</b></span>` : '';
  return `<div class="ai-verdict ${cls}">
    <div class="ai-verdict-head"><span class="ai-verdict-label">⚖️ Penilaian Claude (kalibrator)</span><span class="badge ${cls}">${esc(rec||'-')}</span></div>
    <div class="ai-verdict-meta">
      <span>Keyakinan: <b>${esc(v.keyakinan||'-')}</b></span>
      <span>vs mesin: <b>${esc(vs||'-')}</b> <span class="dim">(${esc(adjStr)})</span></span>
      ${horizon}
    </div>
    ${planHtml}
    ${v.risiko_utama?`<div class="ai-verdict-risk">⚠️ Risiko utama: ${esc(v.risiko_utama)}</div>`:''}
  </div>`;
}

/* ===================== SCREENING ===================== */
function screenTable(rows){
  let r=`<table><thead><tr><th></th><th>Kode</th><th>Sektor</th><th>6 Magic</th><th>CAN SLIM</th><th>Tren</th><th>Stoch RSI (%K)</th><th>Cross</th><th>Aksi</th><th style="text-align:right">Skor</th></tr></thead><tbody>`;
  rows.forEach((s,i)=>{ const tc=s.trend==='UPTREND'?'var(--buy)':s.trend==='DOWNTREND'?'var(--sell)':'var(--mute)';
    const stochGc = (s.stoch_sinyal && s.stoch_sinyal.includes('golden')) ? '<span class="badge buy" style="padding:.1rem .35rem;font-size:.65rem;margin-right:.2rem">Stoch GC</span>' : '';
    const maGc = (s.ma_cross === 'GOLDEN') ? '<span class="badge buy" style="padding:.1rem .35rem;font-size:.65rem">MA GC</span>' : '';
    const crosses = (stochGc || maGc) ? `${stochGc}${maGc}` : '<span class="dim">—</span>';
    
    r+=`<tr style="cursor:pointer" onclick="gotoAnalyze('${s.ticker}')"><td><span class="rank ${i===0?'top':''}">${i+1}</span></td>
      <td><span class="tkr">${s.ticker}</span></td><td class="mut" style="font-size:.78rem">${esc(s.sector)||''}</td>
      <td><div class="flex" style="gap:.5rem"><span class="num">${s.magic_score}/6</span><div style="width:50px">${bar(s.magic_score/6*100)}</div></div></td>
      <td><div class="flex" style="gap:.5rem"><span class="num">${s.canslim_score}/7</span><div style="width:50px">${bar(s.canslim_score/7*100,true)}</div></div></td>
      <td style="font-weight:700;font-size:.78rem;color:${tc}">${s.trend||'—'}</td>
      <td><span class="num" style="font-weight:700">${s.stoch_k != null ? Math.round(s.stoch_k) : '—'}</span><span class="dim" style="font-size:.7rem">%</span></td>
      <td><div class="flex" style="gap:.2rem">${crosses}</div></td>
      <td><span class="badge ${s.css||'na'}">${esc(s.final_signal||s.aksi)}</span>${s.tv_cross_check&&s.tv_cross_check.contradiction?' <span class="badge sell" style="padding:.1rem .3rem;font-size:.6rem;margin-left:.2rem" title="Teknikal TradingView SELL — timing beli berisiko">⚠️TV</span>':''}</td>
      <td style="text-align:right"><b class="num" style="font-size:.95rem">${s.skor}</b></td></tr>`; });
  return r+'</tbody></table>';
}
function gotoAnalyze(tk){
  if(tk==='🪙 EMAS'||tk==='EMAS'){
    document.querySelector('.tab-btn-main[data-p="port"]').click();
    const subBtn = document.querySelector('.sub-tab-btn[data-sub="emas"]');
    if(subBtn) subBtn.click();
    window.scrollTo({top:0,behavior:'smooth'});
    return;
  }
  setTicker(tk);
  document.querySelector('.tab-btn-main[data-p="analyze"]').click();
  const subBtn = document.querySelector('.sub-tab-btn[data-sub="analyze-core"]');
  if(subBtn) subBtn.click();
  analyze();
  window.scrollTo({top:0,behavior:'smooth'});
}

/* ===================== RADAR KONTRADIKSI TRADINGVIEW ===================== */
async function loadCrossCheck(){
  _loaded.cc = true;   // tandai sudah dimuat (cegah auto-load ganda saat pindah tab)
  const body=$('#crosscheck-body'), btn=$('#cc-run');
  if(btn){ btn.disabled=true; btn.textContent='⏳ Memindai…'; }
  body.innerHTML='<div class="empty"><span class="spin"></span> Memindai & menilai akurasi prediksi (backtest) kandidat teratas… (±20-40 dtk)</div>';
  const minacc=($('#cc-minacc')&&$('#cc-minacc').value)||'50';
  let d;
  try{ d=await api('/api/cross-check?top=5&min_acc='+encodeURIComponent(minacc)); }
  catch(e){ body.innerHTML='<div class="empty">Gagal memuat radar.</div>'; if(btn){btn.disabled=false;btn.textContent='▶ Muat Radar';} return; }
  if(btn){ btn.disabled=false; btn.textContent='🔄 Segarkan Radar'; }
  if(!d.enabled){
    body.innerHTML='<p class="sub" style="margin:.4rem 0 0">Cross-check TradingView tidak aktif (mode data bukan <b>hybrid</b>/<b>tradingview</b>). Aktifkan via <code>DATA_SOURCE</code> untuk memunculkan radar ini.</p>';
    return;
  }
  const cands=d.candidates||[], sells=d.sell_signals||[];
  let h=`<div class="cc-summary">
    <div class="cc-stat"><div class="cc-num ok">${d.selaras_count}</div><div class="cc-lbl">Selaras<br>(layak beli)</div></div>
    <div class="cc-stat"><div class="cc-num ${d.tunda_beli_count?'ambernum':''}">${d.tunda_beli_count}</div><div class="cc-lbl">Tunda Beli<br>(teknikal SELL)</div></div>
    <div class="cc-stat"><div class="cc-num ${d.sell_count?'warn':'ok'}">${d.sell_count}</div><div class="cc-lbl">SELL<br>(portofolio)</div></div>
  </div>`;

  // Bagian 1 — TOP-N kandidat trading berakurasi tertinggi (maks N saham/hari).
  const ambang = (Number(d.min_acc)>0) ? ` · ambang akurasi ≥ ${d.min_acc}%` : '';
  h+=`<h3 class="cc-sec">🎯 ${d.top_n} Kandidat Trading — Akurasi Tertinggi <span class="mut" style="font-weight:500;font-size:.72rem">(maks ${d.top_n} saham/hari${ambang})</span></h3>`;
  if(!cands.length){
    // Hanya kosong bila benar-benar tak ada kandidat BELI (pasar lesu / semua AVOID/dimiliki).
    h+='<div class="cc-ok-banner mutbox">Belum ada kandidat BELI saat ini (pasar lesu / semua AVOID atau sudah dimiliki).</div>';
  } else if(d.below_threshold){
    // Tak ada yang lolos ambang → tetap tampilkan akurasi terbaik yang tersedia (peringatan).
    h+=`<div class="cc-note-top amber">⚠️ Tidak ada kandidat dengan akurasi ≥ <b>${d.min_acc}%</b> saat ini — menampilkan <b>${cands.length}</b> dengan <b>akurasi terbaik yang tersedia</b>. Pertimbangkan menunggu setup lebih baik, atau turunkan "Min. akurasi".</div>`;
    h+='<div class="cc-grid">'+cands.map(candCard).join('')+'</div>';
  } else {
    const hid = (d.hidden_by_threshold>0) ? ` <span class="mut">(${d.hidden_by_threshold} kandidat lain di bawah ambang ${d.min_acc}% disembunyikan)</span>` : '';
    h+='<div class="cc-note-top neutral">Diurutkan dari <b>akurasi prediksi</b> (win-rate backtest) tertinggi. ✅ <b>SELARAS</b> = teknikal TradingView mendukung, disertai saran alokasi MM · ⚠️ <b>TUNDA BELI</b> = teknikal TradingView SELL, tunggu konfirmasi.'+hid+'</div>';
    h+='<div class="cc-grid">'+cands.map(candCard).join('')+'</div>';
  }

  // Bagian 2 — Rekomendasi SELL: HANYA untuk saham yang dimiliki (syariah long-only).
  h+='<h3 class="cc-sec" style="margin-top:1.4rem">🔴 Rekomendasi SELL — Posisi di Portofolio</h3>';
  if(!d.portfolio_count){
    h+='<div class="cc-ok-banner mutbox">Portofolio kosong — tidak ada rekomendasi SELL. SELL hanya diberikan untuk saham yang Anda miliki.</div>';
  } else if(!sells.length){
    h+='<div class="cc-ok-banner">✅ Tidak ada posisi portofolio dengan teknikal TradingView SELL saat ini.</div>';
  } else {
    h+='<div class="cc-note-top">Saham milik Anda berikut menunjukkan teknikal TradingView <b>SELL</b> — pertimbangkan exit / kurangi posisi sesuai money management.</div>';
    h+='<div class="cc-grid">'+sells.map(sellCard).join('')+'</div>';
  }

  if((d.held_uncovered||[]).length){
    h+=`<p class="sub" style="margin-top:.9rem">Catatan: ${d.held_uncovered.length} saham milik Anda di luar universe scan (${d.held_uncovered.join(', ')}) — belum dievaluasi radar ini.</p>`;
  }
  body.innerHTML=h;
}
function candCard(x){
  const ra=(x.tv_recommend_all!=null)?Number(x.tv_recommend_all).toFixed(2):'n/a';
  const acc=(x.akurasi_pct!=null)?`${x.akurasi_pct}%`:'—';
  const accN=(x.akurasi_n!=null)?` <span class="dim" style="font-size:.62rem">(${x.akurasi_n} sinyal)</span>`:'';
  const tunda=(x.status==='TUNDA_BELI');
  const statusBadge=tunda?'<span class="cc-flag amber">⚠️ TUNDA BELI</span>':'<span class="cc-flag green">✅ SELARAS</span>';
  let allocHtml='';
  if(!tunda && x.alokasi){
    const a=x.alokasi;
    if(a.lots && a.lots>0){
      const rp=Number(a.outlay_idr||0).toLocaleString('id-ID');
      allocHtml=`<div class="cc-alloc">💰 Alokasi MM: <b>≈ ${a.lots} lot</b>${a.rdn?` @ ${esc(a.rdn)}`:''} · Rp ${rp}${a.pct_cash!=null?` <span class="dim">(${a.pct_cash}% cash)</span>`:''}${(a.net_target_pct!=null)?` · jual +${a.net_target_pct}% utk profit bersih`:''}</div>`;
    } else if(a.catatan){
      allocHtml=`<div class="cc-alloc dim">💰 ${esc(a.catatan)}</div>`;
    }
  }
  return `<div class="cc-card cand-card ${tunda?'warn-card':'ok-card'}" onclick="gotoAnalyze('${x.ticker}')" title="Klik untuk analisa lengkap">
    <div class="cc-card-head"><span class="tkr">${x.ticker}</span>${statusBadge}</div>
    <div class="cc-line"><span class="mut">Akurasi prediksi</span><span><b class="num gain">${acc}</b>${accN}</span></div>
    <div class="cc-line"><span class="mut">Rekomendasi sistem</span><span class="badge ${x.css||'buy'}">${esc(x.aksi||x.final_signal||'-')}</span></div>
    <div class="cc-line"><span class="mut">Teknikal TradingView</span><span class="badge ${tunda?'sell':'buy'}">${esc(x.tv_recommend)} (${ra})</span></div>
    <div class="cc-line"><span class="mut">Fundamental · Skor</span><span>${esc(x.fundamental_label||'-')} · <b class="num">${x.skor!=null?x.skor:'-'}</b></span></div>
    ${allocHtml}
  </div>`;
}
function sellCard(x){
  const ra=(x.tv_recommend_all!=null)?Number(x.tv_recommend_all).toFixed(2):'n/a';
  const pl=(x.pl_pct!=null)?`<b class="${x.pl_pct>=0?'gain':'loss'}">${x.pl_pct>=0?'+':''}${x.pl_pct}%</b>`:'—';
  const typeBadge=(x.pos_type==='investasi')?' <span class="badge hold" style="font-size:.58rem;padding:.08rem .3rem">INVESTASI</span>':'';
  return `<div class="cc-card sell-card" onclick="gotoAnalyze('${x.ticker}')" title="Klik untuk analisa lengkap">
    <div class="cc-card-head"><span class="tkr">${x.ticker}${typeBadge}</span><span class="cc-flag">🔴 SELL</span></div>
    <div class="cc-line"><span class="mut">Teknikal TradingView</span><span class="badge sell">${esc(x.tv_recommend)} (${ra})</span></div>
    <div class="cc-line"><span class="mut">Posisi Anda</span><span><b class="num">${x.lots!=null?x.lots:'-'}</b> lot · P/L ${pl}</span></div>
    <div class="cc-line"><span class="mut">Fundamental · Skor</span><span>${esc(x.fundamental_label||'-')} · <b class="num">${x.skor!=null?x.skor:'-'}</b></span></div>
  </div>`;
}

/* ===================== SCREENER UNDERVALUE ===================== */
async function runUndervalue(){
  const top=+$('#uv-top').value||6, min=+$('#uv-min').value||55, pbv=+$('#uv-pbv').value||0,
        hor=+$('#uv-hor').value||20, tgt=+$('#uv-tgt').value||7;
  const btn=$('#uv-run'), orig=btn.textContent; btn.disabled=true; btn.textContent='⏳ Memindai…';
  $('#uv-status').innerHTML='<span class="spin"></span> Memindai SELURUH saham syariah: valuasi + backtest historis… (±20-30 dtk)';
  $('#uv-out').innerHTML='';
  const q=new URLSearchParams({top,min_score:min,horizon:hor,target_pct:tgt});
  if(pbv>0) q.set('max_pbv',pbv);
  try{ const d=await api('/api/undervalue/screen?'+q); renderUndervalue(d); }
  catch(e){ $('#uv-status').innerHTML=`<span style="color:var(--sell)">Gagal: ${e}</span>`; }
  finally{ btn.disabled=false; btn.textContent=orig; }
}
function renderUndervalue(d){
  $('#uv-status').innerHTML=`Memindai <b>${d.scanned}/${d.universe_size}</b> saham syariah${d.errors?` · ${d.errors} gagal data`:''} → <b>${d.rec_count}</b> aksi kuat.`;
  const recs=d.recommendations||[];
  let html=`<p class="sub" style="margin:.2rem 0 1rem">📐 ${esc(d.metodologi)}</p>`;
  // --- Rekomendasi Kuat (BUY/SELL) ---
  html+=`<h3 class="sec" style="margin:.2rem 0 .7rem">🎯 Rekomendasi Kuat (Top ${d.params.top})</h3>`;
  html+= recs.length ? recs.map(uvRec).join('')
       : '<div class="empty">Belum ada aksi kuat. Turunkan ambang BUY atau tunggu sinyal.</div>';
  // --- Seluruh saham ter-ranking (transparansi) ---
  html+=`<details style="margin-top:1.4rem"><summary class="sec" style="cursor:pointer">📋 Seluruh ${d.count} saham syariah ter-ranking (klik untuk lihat)</summary>
    <div style="margin-top:.8rem">${d.candidates.map((c,i)=>uvCard(c,i)).join('')}</div></details>`;
  $('#uv-out').innerHTML=html;
}
function uvRec(r){
  const buy=r.action==='BUY', m=r.metrics||{}, bt=r.backtest||{};
  const own = r.owned ? `<span class="badge ${(r.pnl_pct||0)>=0?'buy':'sell'}">DIMILIKI · P/L ${r.pnl_pct>=0?'+':''}${r.pnl_pct}%</span>` : '<span class="badge na">belum dimiliki</span>';
  const winTxt = bt.win_rate!=null ? `win ${bt.win_rate}% (n=${bt.n_signals}), avg ${bt.avg_return}%` : 'validasi historis tipis';
  const planTxt = (buy && r.plan) ? `🎯 Entry ${fmt(r.plan.entry)} · 🛑 Stop ${fmt(r.plan.stop_loss)} (-${r.plan.risk_pct}%) · 🎁 Target ${fmt(r.plan.target)} (+${r.plan.reward_pct}%) · RRR ${r.plan.rrr}` : esc(r.next_step||'');
  return `<div class="glass-panel" style="margin-bottom:.7rem;padding:.9rem 1.1rem;border-left:4px solid ${buy?'var(--buy)':'var(--sell)'}">
    <div class="between" style="align-items:flex-start">
      <div class="flex" style="gap:.55rem;flex-wrap:wrap">
        <span class="badge ${buy?'buy':'sell'}" style="font-size:.78rem">${r.action}</span>
        <span class="tkr" style="cursor:pointer" onclick="gotoAnalyze('${r.ticker}')">${r.ticker}</span>
        ${own}
        ${(buy && r.label)?`<span class="badge ${r.css}" title="kekuatan undervalue">${esc(r.label)}</span>`:''}
      </div>
      <div style="text-align:right"><div style="font-size:1.2rem;font-weight:800;line-height:1">${r.conviction}</div>
        <div class="mut" style="font-size:.64rem">keyakinan</div></div>
    </div>
    <div class="mut" style="font-size:.78rem;margin:.25rem 0 .45rem">${esc(r.name||'')} · ${esc(r.sector||'')} · harga ${fmt(r.price)}</div>
    <div style="font-size:.8rem;margin-bottom:.4rem">${esc(r.reason)}</div>
    <div class="flex" style="gap:.9rem;flex-wrap:wrap;font-size:.74rem;color:var(--mute)">
      <span>PBV ${m.pbv??'–'}</span><span>PER ${m.per??'–'}</span><span>Div ${m.dividend_yield??'–'}%</span><span>${winTxt}</span>
    </div>
    <div style="font-size:.76rem;margin-top:.45rem;padding-top:.4rem;border-top:1px solid var(--line)">${planTxt}
      <button class="btn ghost" style="margin-left:.6rem;padding:.25rem .6rem;font-size:.72rem" onclick="uvAdvisor('${r.ticker}',this)">🤖 Narasi AI</button>
    </div>
    <div class="uv-ai" style="margin-top:.5rem"></div>
  </div>`;
}
function uvNum(v,suf){ return (v===null||v===undefined)?'<span class="mut">–</span>':('<b>'+v+(suf||'')+'</b>'); }
function uvCard(c,i){
  const m=c.metrics, bt=c.backtest, pl=c.plan, ex=c.valuation_extra||{};
  const win = bt.win_rate!=null ? `${bt.win_rate}% <span class="mut">(n=${bt.n_signals})</span>` : '<span class="mut">data kurang</span>';
  const avgC = (bt.avg_return||0)>=0?'var(--buy)':'var(--sell)';
  return `<div class="glass-panel" style="margin-bottom:.8rem;padding:1rem 1.2rem">
    <div class="between" style="align-items:flex-start">
      <div class="flex" style="gap:.6rem;flex-wrap:wrap">
        <span class="rank ${i===0?'top':''}">${i+1}</span>
        <span class="tkr" style="cursor:pointer" onclick="gotoAnalyze('${c.ticker}')">${c.ticker}</span>
        <span class="badge ${c.css}">${esc(c.label)}</span>
        ${c.downtrend?'<span class="badge sell" title="masih downtrend — hati-hati value trap">↓ downtrend</span>':''}
        ${c.backtest_thin?'<span class="badge warning" title="bukti backtest historis sedikit — skor dihukum">⚠ backtest tipis</span>':''}
        ${c.sharia_warning?'<span class="badge warning" title="status syariah perlu cek manual">⚠ syariah</span>':''}
      </div>
      <div style="text-align:right"><div style="font-size:1.55rem;font-weight:800;line-height:1">${c.score}</div>
        <div class="mut" style="font-size:.66rem">AI Undervalue Score</div></div>
    </div>
    <div class="mut" style="font-size:.8rem;margin:.25rem 0 .7rem">${esc(c.name||'')} · ${esc(c.sector||'')} · harga ${fmt(c.price)}</div>
    <div class="grid g-3" style="gap:.6rem;font-size:.76rem;margin-bottom:.6rem">
      <div>Valuasi ${uvNum(c.valuation_score)}${bar(c.valuation_score||0)}</div>
      <div>Timing ${uvNum(c.timing_score)}${bar(c.timing_score||0,true)}</div>
      <div>Backtest ${uvNum(c.backtest_confidence)}${bar(c.backtest_confidence||0)}</div>
    </div>
    <div class="flex" style="gap:.9rem;flex-wrap:wrap;font-size:.77rem">
      <span>PBV ${uvNum(m.pbv)}</span><span>PER ${uvNum(m.per)}</span><span>PEG ${uvNum(m.peg)}</span>
      <span>ROE ${uvNum(m.roe,'%')}</span><span>DER ${uvNum(m.der,'%')}</span><span>Div ${uvNum(m.dividend_yield,'%')}</span>
      ${ex.margin_of_safety_pct!=null?`<span title="vs angka Graham">MoS ${uvNum(ex.margin_of_safety_pct,'%')}</span>`:''}
    </div>
    <div class="flex" style="gap:.9rem;flex-wrap:wrap;font-size:.77rem;margin-top:.45rem">
      <span class="mut">Backtest ${bt.horizon_days}h · entry RSI&lt;${bt.oversold_rsi}:</span>
      <span>win ${win}</span><span>avg <b style="color:${avgC}">${bt.avg_return!=null?bt.avg_return+'%':'–'}</b></span>
      <span>median ${uvNum(bt.median_return,'%')}</span>
    </div>
    <div class="flex" style="gap:.9rem;flex-wrap:wrap;font-size:.77rem;margin-top:.5rem;padding-top:.55rem;border-top:1px solid var(--line)">
      <span>🎯 Entry ${uvNum(pl.entry)}</span><span>🛑 Stop ${uvNum(pl.stop_loss)} <span class="mut">(-${pl.risk_pct}%)</span></span>
      <span>🎁 Target ${uvNum(pl.target)} <span class="mut">(+${pl.reward_pct}%)</span></span><span>RRR ${uvNum(pl.rrr)}</span>
      <button class="btn ghost" style="margin-left:auto;padding:.3rem .7rem;font-size:.74rem" onclick="uvAdvisor('${c.ticker}',this)">🤖 Narasi AI</button>
    </div>
    <div class="uv-ai" style="margin-top:.6rem"></div>
  </div>`;
}
async function uvAdvisor(tk, btn){
  const box=btn.closest('.glass-panel').querySelector('.uv-ai');
  const eng=(document.querySelector('#adv-engine')||{}).value||'auto';
  box.innerHTML='<div class="flex"><span class="spin"></span><span class="dim">Advisor menyusun narasi untuk '+tk+'…</span></div>';
  try{ const d=await api('/api/advisor/'+tk+'?engine='+eng);
    if(d.enabled===false){ box.innerHTML='<p class="dim">'+esc(d.message||'Advisor nonaktif.')+'</p>'; return; }
    if(d.error){ box.innerHTML='<p style="color:var(--sell)">'+esc(d.error)+'</p>'; return; }
    box.innerHTML='<div class="ai-box" style="padding:.8rem 1rem;border-radius:12px"><div class="mut" style="font-size:.7rem;margin-bottom:.3rem">✦ '+esc(d.model||'')+'</div><div class="ai-text">'+mdb(d.analisa)+'</div></div>';
  }catch(e){ box.innerHTML='<p class="dim">Gagal memuat narasi: '+e+'</p>'; }
}
async function screen(){
  const params = {};
  const potensi = $('#potensi').value;
  if (potensi !== 'semua') params.potensi = potensi;
  const goldenCross = $('#golden_cross').value;
  if (goldenCross !== 'abaikan') params.golden_cross = goldenCross;
  const stochRange = $('#stoch_range').value;
  if (stochRange !== 'abaikan') params.stoch_rsi_range = stochRange;

  const q = new URLSearchParams(params);
  $('#sst').innerHTML='<span class="spin"></span> Memproses…'; $('#sout').innerHTML='';
  try{ const d=await api('/api/screen?'+q); LAST_SCREEN=d.hasil;
    $('#sst').innerHTML=`<b style="color:var(--brand-2)">${d.jumlah_lolos}</b> dari ${d.jumlah_universe} saham lolos kriteria.`;
    $('#sout').innerHTML=d.hasil.length?`<section class="glass-panel">${screenTable(d.hasil)}</section>`:'<section class="glass-panel"><div class="empty">Tidak ada yang lolos. Longgarkan kriteria.</div></section>';
  }catch(e){ $('#sout').innerHTML='<section class="glass-panel"><div class="empty">Gagal memproses.</div></section>'; }
}
function exportScreen(){
  if(!LAST_SCREEN.length){ toast('Jalankan screening / decision center dulu.'); return; }
  const hdr=['ticker','name','sector','magic_score','canslim_score','trend','stoch_k','stoch_sinyal','ma_cross','aksi','skor'];
  const rows=LAST_SCREEN.map(s=>hdr.map(k=>`"${(s[k]??'').toString().replace(/"/g,'""')}"`).join(','));
  const csv=hdr.join(',')+'\n'+rows.join('\n');
  const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download='screening_syariah.csv'; a.click(); toast('CSV diunduh ('+LAST_SCREEN.length+' saham).');
}

/* ===================== TRADING PLAN ===================== */
function kvCard(o,skip){ let r='<table>'; for(const k in o){ if(typeof o[k]==='object'||(skip||[]).includes(k))continue;
  r+=`<tr><td class="mut" style="text-transform:capitalize">${k.replace(/_/g,' ')}</td><td style="text-align:right" class="num"><b>${typeof o[k]==='number'?fmt(o[k]):esc(o[k])}</b></td></tr>`;} return r+'</table>'; }
function miniStat(l,v,s){ return `<div class="cardlet"><div class="lbl mut" style="font-size:.7rem;text-transform:uppercase">${l}</div><div class="num" style="font-size:1.1rem;font-weight:800;margin-top:.1rem">${v}</div><div class="sub">${s}</div></div>`; }
async function mm(){
  const d=await post('/api/plan/money-management',{idle_money:+$('#idle').value,num_stocks:+$('#nstk').value,risk_pct:+$('#risk').value,profit_pct:+$('#profit').value});
  const k=d.keterangan||{};
  let html='';
  if(d.aturan && d.aturan.length) html+=d.aturan.map(a=>`<div class="badge hold" style="display:block;margin-bottom:.45rem">⚠ ${esc(a)}</div>`).join('');
  html+=`<div class="grid g-3" style="gap:.5rem;margin-bottom:.8rem">
    ${miniStat('Beli / Emiten',fmt(d.kemampuan_beli_per_emiten),d.jumlah_saham+' emiten')}
    ${miniStat('Potensi Risk',fmt(d.potensi_risk_per_emiten),d.risk_pct+'%')}
    ${miniStat('Potensi Profit',fmt(d.potensi_profit_per_emiten),d.profit_pct+'%')}</div>`;
  const row=(nm,val,sub,desc,cls)=>`<div class="crow" title="${esc(desc||'')}"><div style="min-width:0"><div class="nm">${nm}</div><div class="tg">${esc(sub)}</div></div><b class="num ${cls||''}" style="font-size:1.02rem">${fmt(val)}</b></div>`;
  html+=`<div class="tg" style="font-weight:700;margin-bottom:.2rem">MONEY MANAGEMENT RESULT</div>
    ${row('Idle Fund',d.idle_fund,'= Modal',k.idle_fund)}
    ${row('Trading Fund',d.trading_fund,d.trading_fund_pct+'% × Idle Fund',k.trading_fund)}
    ${row('Bid Fund',d.bid_fund,'Trading Fund ÷ '+d.jumlah_saham,k.bid_fund)}
    ${row('Loss Fund',d.loss_fund,'Bid Fund × '+d.risk_pct+'%',k.loss_fund,'pl-down')}
    ${row('Profit Fund',d.profit_fund,'Bid Fund × '+d.profit_pct+'%',k.profit_fund,'pl-up')}
    <p class="sub">${esc(d.catatan)}</p>`;
  $('#mmout').innerHTML=html;
  return d;
}
async function taichi(){ const d=await post('/api/plan/taichi',{modal:+$('#tmodal').value,market_price:+$('#tmp').value,risk_pct:+$('#trisk').value,mode:$('#tmode').value});
  if(d.error){ $('#tout').innerHTML=`<p style="color:var(--sell)">${esc(d.error)}</p>`; return; }
  let r=`<div class="between" style="margin-bottom:.5rem"><span class="badge brand">${d.mode} · risk ${d.risk_pct}%</span><span class="dim">Total ${d.total_lot} lot · avg <b class="num" style="color:var(--text)">${fmt(d.average_jika_full)}</b></span></div>
    <table><thead><tr><th>Titik</th><th style="text-align:right">Harga</th><th style="text-align:right">Lot</th><th style="text-align:right">Nilai</th></tr></thead><tbody>`;
  d.open_buy.forEach(o=>r+=`<tr><td><b>${o.titik}</b></td><td style="text-align:right" class="num">${fmt(o.harga)}</td><td style="text-align:right" class="num">${o.lot}</td><td style="text-align:right" class="num">${fmt(o.nilai)}</td></tr>`);
  r+=`</tbody></table><p class="sub">Cash/CL: <b class="num">${fmt(d.cash_cl_area)}</b> · ${esc(d.catatan)}</p>`; $('#tout').innerHTML=r; }
async function rrr(){
  const d=await post('/api/plan/rrr',{buy:+$('#rbuy').value,risk_pct:+$('#rrisk').value,profit_pct:+$('#rprofit').value});
  if(d.error){ $('#rout').innerHTML=`<p style="color:var(--sell)">${esc(d.error)}</p>`; return; }
  let warn=(d.aturan&&d.aturan.length)?d.aturan.map(a=>`<div class="badge hold" style="display:block;margin-bottom:.4rem">⚠ ${esc(a)}</div>`).join(''):'';
  const row=(l,v,cls)=>`<div class="crow"><span class="nm">${l}</span><b class="num ${cls||''}">${fmt(v)}</b></div>`;
  $('#rout').innerHTML=warn+`<div class="between" style="align-items:center;margin-bottom:.6rem"><div style="font-size:1.6rem;font-weight:800">${esc(d.rrr)}</div>
    ${d.layak?'<span class="badge buy">Layak ✓</span>':'<span class="badge hold">&lt; 1:2</span>'}</div>
    ${row('Harga Beli',d.harga_beli)}${row('Cut Loss (−'+d.risk_pct+'%)',d.cut_loss,'pl-down')}${row('Take Profit (+'+d.profit_pct+'%)',d.take_profit,'pl-up')}
    ${row('Risk / lembar',d.risk_per_lembar,'pl-down')}${row('Reward / lembar',d.reward_per_lembar,'pl-up')}
    <p class="sub">${esc(d.catatan)}</p>`; }

/* ===================== PEDOMAN ===================== */
function loadPedoman(){
  $('#ped-body').innerHTML = `
  <div class="panel-header"><h2>📜 Pedoman Trading Saham Syariah</h2></div>
  <p class="dim">Ringkasan metodologi dari <i>Sharia Investment and Trading Module</i> (Doddy Eka Putra / YLive Academy) & Fatwa DSN-MUI.</p>

  <div class="panel-header"><h2>🎓 Teori Dasar Trading Saham &amp; Saham Syariah</h2></div>
  <p class="dim">Penjelasan bahasa sederhana untuk pemula — fondasi sebelum masuk ke metodologi &amp; teknis di bawah.</p>

  <h4>0.1 Apa itu Saham &amp; Trading?</h4>
  <ul>
    <li><b>Saham</b> = tanda kepemilikan sebagian sebuah perusahaan terbuka (Tbk). Memegang saham BBCA berarti Anda ikut memiliki sepotong kecil bank tersebut.</li>
    <li><b>Emiten</b> = perusahaan yang sahamnya diperjualbelikan di bursa.</li>
    <li><b>Bursa Efek Indonesia (BEI/IDX)</b> = "pasar" resmi tempat jual-beli saham; buka Senin–Jumat (kecuali libur), 2 sesi.</li>
    <li><b>Investasi vs Trading</b>: investasi = menyimpan saham lama (tahunan) untuk pertumbuhan; <b>trading</b> = jual-beli jangka pendek (harian–mingguan) memanfaatkan selisih harga.</li>
    <li><b>Dua sumber untung</b>: <i>capital gain</i> (jual lebih tinggi dari beli) &amp; <i>dividen</i> (bagi hasil laba perusahaan).</li>
    <li><b>1 lot = 100 lembar.</b> Transaksi lewat <b>broker/sekuritas</b>; dana Anda disimpan di <b>RDN</b> (Rekening Dana Nasabah).</li>
  </ul>

  <h4>0.2 Apa itu Saham Syariah?</h4>
  <ul>
    <li>Saham yang <b>memenuhi prinsip Islam</b>: bidang usaha halal + rasio keuangan sehat, terdaftar di <b>Daftar Efek Syariah (DES)/ISSI</b> oleh OJK.</li>
    <li><b>Yang dihindari</b>: <i>riba</i> (bunga/margin), <i>gharar &amp; maysir</i> (spekulasi/judi), <i>short selling</i> (menjual yang belum dimiliki), serta emiten haram (miras, rokok, bank konvensional, judi, dll).</li>
    <li>Praktik: <b>tunai &amp; long-only</b> — beli dulu baru jual, tanpa pinjaman berbunga. (Fatwa DSN-MUI No. 40/2003 &amp; 80/2011.)</li>
  </ul>

  <h4>0.3 Kerangka Berpikir — 4 Pertanyaan</h4>
  <p><b>WHAT</b> (saham apa? syariah &amp; sehat) → <b>WHY</b> (kenapa layak? fundamental) → <b>WHEN</b> (kapan masuk? teknikal/timing) → <b>HOW</b> (berapa &amp; batas risiko? money management). Prinsip: <i>"rencanakan yang Anda tradingkan, tradingkan yang Anda rencanakan."</i></p>

  <h4>0.4 Kamus Istilah Trading (bahasa sederhana)</h4>
  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Pasar &amp; dasar</b></p>
  <ul>
    <li><b>IHSG</b> — indeks rata-rata harga seluruh saham BEI; cermin arah pasar naik/turun.</li>
    <li><b>Kapitalisasi pasar</b> — ukuran perusahaan = harga × jumlah saham; yang besar &amp; mapan disebut <b>blue chip</b>.</li>
    <li><b>Likuiditas</b> — seberapa ramai saham diperdagangkan; likuid = mudah dijual tanpa banting harga.</li>
    <li><b>Volume</b> — banyaknya lembar berpindah tangan; lonjakan volume = minat besar.</li>
    <li><b>Volatilitas</b> — seberapa liar harga naik-turun; tinggi = peluang untung &amp; rugi sama-sama besar.</li>
    <li><b>IPO</b> — saat perusahaan pertama kali menjual sahamnya ke publik.</li>
    <li><b>T+2</b> — dana hasil penjualan cair 2 hari bursa setelah transaksi.</li>
  </ul>
  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Harga &amp; order</b></p>
  <ul>
    <li><b>Bid</b> harga yang ingin dibayar pembeli; <b>Offer/Ask</b> harga yang diminta penjual; <b>Spread</b> = selisih keduanya.</li>
    <li><b>ARA / ARB</b> — Auto Reject Atas/Bawah: batas maksimum kenaikan/penurunan harga dalam sehari.</li>
  </ul>
  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Arah &amp; level harga</b></p>
  <ul>
    <li><b>Bullish</b> suasana optimis (harga cenderung naik); <b>Bearish</b> pesimis (cenderung turun).</li>
    <li><b>Uptrend / Downtrend / Sideways</b> — tren naik / turun / mendatar.</li>
    <li><b>Support</b> = "lantai" (harga sering memantul naik); <b>Resistance</b> = "atap" (harga sering tertahan).</li>
    <li><b>Breakout</b> — harga menembus resistance dengan volume → potensi melanjutkan naik.</li>
  </ul>
  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Aksi &amp; manajemen posisi</b></p>
  <ul>
    <li><b>Entry / Exit</b> — titik masuk (beli) / keluar (jual).</li>
    <li><b>Cut Loss (Stop Loss)</b> — jual rugi terencana untuk membatasi kerugian (disiplin!); di app ambang −7%.</li>
    <li><b>Take Profit</b> — jual saat target untung tercapai; di app +20% / target Jalur 7%.</li>
    <li><b>Trailing stop</b> — batas jual yang ikut naik mengunci profit saat harga naik.</li>
    <li><b>Average down</b> — menambah beli saat harga turun agar harga rata-rata turun (berisiko bila tren masih turun).</li>
    <li><b>RRR (Risk-Reward Ratio)</b> — perbandingan potensi rugi : untung; idealnya minimal 1:2.</li>
  </ul>
  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Untung-rugi &amp; portofolio</b></p>
  <ul>
    <li><b>Floating / Unrealized P/L</b> — untung-rugi "di atas kertas" (posisi belum dijual).</li>
    <li><b>Realized P/L</b> — untung-rugi nyata setelah posisi dijual.</li>
    <li><b>ROI (Return on Investment)</b> — persentase imbal hasil terhadap modal. Sistem ini menggunakan **ROI Integral** yang menggabungkan P/L bersih transaksi masa lalu (<i>Realized</i>) dan posisi aktif berjalan saat ini (<i>Unrealized</i>) demi mengukur performa akumulasi modal yang objektif tanpa bias jangka pendek.</li>
    <li><b>Diversifikasi</b> — menyebar modal ke beberapa emiten agar risiko tidak menumpuk di satu saham.</li>
    <li><b>Money Management</b> — aturan berapa modal per transaksi &amp; batas risiko; gunakan <b>uang dingin</b> saja.</li>
  </ul>

  <h4>0.5 Panduan Visual: Cara Membaca Grafik &amp; Indikator</h4>
  <p class="dim">Panduan praktis untuk memahami visualisasi grafik dan indikator yang tampil di tab <b>Analisa Saham</b> dan <b>Dashboard</b>.</p>
  <ul>
    <li><b>1. Grafik Candlestick (Lilin Harga)</b>:
      <br>
      • Tiap batang lilin mewakili pergerakan harga dalam 1 hari.
      <br>
      • <b>Badan (Body) Hijau</b>: Harga penutupan lebih tinggi dari pembukaan (harga naik).
      <br>
      • <b>Badan (Body) Merah</b>: Harga penutupan lebih rendah dari pembukaan (harga turun).
      <br>
      • <b>Ekor/Sumbu (Wick/Shadow)</b>: Menunjukkan harga tertinggi dan terendah yang sempat dicapai hari itu. Ekor bawah yang panjang menandakan tekanan beli yang kuat (harga ditolak jatuh).
    </li>
    <li><b>2. Garis MA (Moving Average / Rata-rata Bergerak)</b>:
      <br>
      • <b>SMA 20 (Garis Hijau)</b>: Tren jangka pendek (~1 bulan). Selama harga di atas garis ini, momentum jangka pendek sedang naik (Bullish).
      <br>
      • <b>SMA 50 (Garis Biru)</b>: Tren jangka menengah (~2,5 bulan). Batas pertahanan tren menengah.
      <br>
      • <b>SMA 200 (Garis Ungu)</b>: Tren jangka panjang (~1 tahun). <b>Ini adalah batas hidup-mati tren</b>. Jika harga di bawah SMA 200, saham dalam kondisi <i>Downtrend</i> parah — <b>sistem akan menyarankan untuk dihindari (AVOID)</b>.
    </li>
    <li><b>3. Zona Support &amp; Resistance (Latar Belakang Bergaris)</b>:
      <br>
      • <b>Support (Zona Hijau di Bawah)</b>: Area "lantai" harga. Tempat pembeli biasanya mulai menumpuk order untuk memicu pantulan naik.
      <br>
      • <b>Resistance (Zona Merah di Atas)</b>: Area "atap" harga. Tempat penjual biasanya mulai melepas saham untuk memicu penurunan harga.
      <br>
      • <b>Kekuatan (●●●)</b>: Jumlah titik hitam menandakan seberapa sering level tersebut diuji. Makin banyak titik, makin kuat zona tersebut.
    </li>
    <li><b>4. Grafik Volume (Batang di Bawah Candlestick)</b>:
      <br>
      • Menunjukkan jumlah lot saham yang berpindah tangan setiap hari.
      <br>
      • <b>Volume Spike (Lonjakan Volume)</b>: Jika volume harian melebihi 1,5× rata-rata 20 hari, ini adalah tanda <b>uang besar (Smart Money / Bandar) sedang masuk atau keluar</b>. Breakout yang disertai lonjakan volume memiliki akurasi sangat tinggi.
    </li>
    <li><b>5. Indikator Stochastic RSI (Momentum)</b>:
      <br>
      • Bergerak di rentang 0 hingga 100 untuk mengukur kejenuhan pasar.
      <br>
      • <b>Overbought (Jenuh Beli) &gt; 80</b>: Harga sudah naik terlalu cepat dan rentan koreksi/turun.
      <br>
      • <b>Oversold (Jenuh Jual) &lt; 20</b>: Harga sudah turun terlalu dalam dan berpotensi memantul naik (<i>rebound</i>).
      <br>
      • <b>Persilangan (%K memotong %D)</b>: Persilangan garis biru (%K) ke atas garis merah (%D) di area di bawah 20 (<i>Golden Cross</i>) adalah sinyal beli yang kuat.
    </li>
    <li><b>6. Indikator ADX (Average Directional Index - Kekuatan Tren)</b>:
      <br>
      • Mengukur <b>seberapa kuat tren berjalan</b>, tanpa memedulikan arahnya (naik atau turun).
      <br>
      • <b>Nilai &lt; 20</b>: Tren lemah atau pasar sedang bergerak mendatar (<i>Sideways/Consolidation</i>).
      <br>
      • <b>Nilai &gt; 25</b>: Tren sedang berjalan kuat. Sangat bagus untuk strategi <i>trend following</i>.
      <br>
      • <b>Nilai &gt; 40</b>: Tren sangat ekstrem/kuat.
    </li>
    <li><b>7. Indikator ATR (Average True Range - Volatilitas)</b>:
      <br>
      • Mengukur rentang pergerakan harga rata-rata harian dalam Rupiah.
      <br>
      • Digunakan untuk menentukan <b>jarak pengaman batas rugi (Stop Loss / Cut Loss)</b>. Rumus standar yang aman adalah menempatkan Cut Loss sejauh 2 × ATR di bawah harga beli Anda agar tidak terkena fluktuasi harian (<i>noise</i>).
    </li>
    <li><b>8. Proyeksi Fibonacci Retracement &amp; Time Zone (Astronacci Syariah)</b>:
      <br>
      • <b>Fibonacci Retracement (Level Harga)</b>: Menampilkan level support potensial saat harga terkoreksi (Golden Ratio <b>61.8%</b> adalah area beli terbaik karena harga cenderung memantul di sini).
      <br>
      • <b>Fibonacci Time Zone (Target Tanggal)</b>: Memproyeksikan perkiraan tanggal siklus pembalikan arah berikutnya (reversal) berdasarkan deret Fibonacci bursa. Hitung mundur hari bursa membantu Anda bersiap sebelum harga berbalik arah.
    </li>
    <li><b>9. Grafik Tren IHSG (Market Direction)</b>:
      <br>
      • Berfungsi sebagai penunjuk arah mata angin pasar secara keseluruhan.
      <br>
      • Berwarna <b>Hijau</b> saat IHSG berada di atas SMA 200 (Uptrend): Pasar aman untuk membeli saham syariah agresif.
      <br>
      • Berwarna <b>Merah</b> saat IHSG berada di bawah SMA 200 (Downtrend): Pasar lesu/berisiko tinggi. AI akan otomatis mengerem rekomendasi beli dan menyarankan pengalihan dana ke emas safe-haven.
    </li>
  </ul>

  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Rasio fundamental (kesehatan perusahaan)</b></p>
  <ul>
    <li><b>EPS</b> — laba bersih per lembar saham; makin tumbuh makin baik.</li>
    <li><b>PER</b> — harga ÷ EPS, kasarnya "berapa tahun balik modal"; kecil = relatif murah.</li>
    <li><b>PBV</b> — harga ÷ nilai buku per lembar; &lt;1 = dihargai di bawah nilai bukunya (murah).</li>
    <li><b>ROE / ROA</b> — seberapa untung perusahaan dari modal / aset; makin tinggi makin efisien.</li>
    <li><b>DER</b> — utang ÷ modal; kecil = lebih aman.</li>
    <li><b>Dividend Yield</b> — dividen setahun ÷ harga; semacam "bunga" dari memegang saham.</li>
  </ul>
  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Indikator teknikal (membaca timing)</b></p>
  <ul>
    <li><b>MA / SMA / EMA</b> — garis rata-rata harga (mis. 20/50/200 hari) untuk melihat arah tren.</li>
    <li><b>Golden Cross / Death Cross</b> — MA pendek memotong ke atas / ke bawah MA panjang → sinyal beli / jual.</li>
    <li><b>RSI</b> (0–100) — momentum; &gt;70 <b>overbought</b> (kemahalan), &lt;30 <b>oversold</b> (kemurahan).</li>
    <li><b>MACD</b> — selisih dua EMA; memotong ke atas = momentum menguat.</li>
    <li><b>Stochastic</b> — posisi harga dalam rentangnya; golden cross di area oversold = sinyal beli.</li>
    <li><b>Candlestick</b> — batang "lilin" harga (buka–tutup–tinggi–rendah); pola Hammer/Engulfing menandai pembalikan arah.</li>
  </ul>
  <p class="dim" style="margin:.4rem 0 .1rem"><b>▸ Psikologi (musuh utama trader)</b></p>
  <ul>
    <li><b>FOMO</b> (Fear of Missing Out) — membeli karena takut ketinggalan, padahal harga sudah tinggi.</li>
    <li><b>Panic selling</b> — menjual rugi karena panik, bukan karena rencana.</li>
    <li><b>Disiplin</b> — patuhi rencana &amp; cut-loss; emosi dikendalikan oleh aturan — itulah fungsi aplikasi ini.</li>
  </ul>

  <hr style="margin:1.4rem 0;border:none;border-top:1px solid var(--line)">
  <div class="panel-header"><h2>📐 Metodologi (Modul &amp; Fatwa)</h2></div>
  <h4>1. Kepatuhan Syariah (Fatwa DSN-MUI)</h4>
  <ul><li>Hanya saham di <b>Daftar Efek Syariah (DES/ISSI)</b> — usaha halal.</li>
    <li>Rasio utang berbasis bunga / total aset <b>≤ 45%</b>; pendapatan non-halal / total <b>≤ 10%</b>.</li>
    <li>Transaksi <b>tunai & long-only</b>: tanpa margin (riba), short selling, bai' al-ma'dum, najsy, ghisysy, insider trading, pump-and-dump <span class="dim">(Fatwa No. 80/2011)</span>.</li></ul>
  <h4>2. 6 Magic Number (Fundamental)</h4>
  <ul><li>EPS positif & tumbuh konsisten</li><li>ROA &gt; 15% · ROE &gt; 15%</li><li>DER &lt; 1 (100%)</li>
    <li>PBV &lt; 1 (BVPS &gt; harga = undervalue)</li><li>PER &lt; 10×</li><li>Bonus: Dividend Yield &gt; 7%</li></ul>
  <h4>3. CAN SLIM (William O'Neil)</h4>
  <ul><li><b>C</b> — Current Earning Quarterly YoY &gt; 25%</li><li><b>A</b> — Annual Earning &gt; 25% (3 thn) & ROE &gt; 17%</li>
    <li><b>N</b> — New product/manajemen, dekat ATH + volume</li><li><b>S</b> — Supply &amp; Demand (market cap, free float kecil)</li>
    <li><b>L</b> — Leader sektor (relative strength &gt; IHSG)</li><li><b>I</b> — Institutional sponsorship</li>
    <li><b>M</b> — Market Direction (IHSG &gt; SMA200, Wyckoff akumulasi/uptrend)</li></ul>
  <h4>4. Analisa Teknikal</h4>
  <ul><li><b>SMA 200</b> — harga di atas = uptrend (kandidat), di bawah = hindari.</li>
    <li><b>Stochastic</b> — %K/%D; OB &gt; 80, OS &lt; 20; <i>golden cross</i> di area oversold = sinyal beli.</li>
    <li><b>Support/Resistance & Trendline</b>; pola candlestick reversal (Hammer, Engulfing, Morning/Evening Star, Harami).</li></ul>

  <div class="panel-header" style="margin-top:1rem"><h2>📏 Analisa Teknikal: Support &amp; Resistance</h2></div>
  <p class="dim">Materi inti untuk membaca <b>kapan masuk &amp; keluar</b> (WHEN). Support &amp; Resistance (S/R) adalah level harga di mana tekanan beli/jual cenderung berbalik — fondasi semua teknik entry, cut-loss, dan target di aplikasi ini.</p>

  <h4>4a. Konsep Dasar</h4>
  <ul>
    <li><b>Support</b> = "lantai" — area di mana permintaan (beli) menguat sehingga penurunan harga cenderung tertahan lalu memantul naik.</li>
    <li><b>Resistance</b> = "atap" — area di mana penawaran (jual) menguat sehingga kenaikan harga cenderung tertahan lalu berbalik turun.</li>
    <li><b>Bukan garis tunggal, tapi zona.</b> Harga jarang berbalik di angka persis sama; perlakukan S/R sebagai <i>area</i> (rentang) — itulah sebabnya aplikasi meng-<i>cluster</i> beberapa titik berdekatan menjadi satu zona.</li>
    <li><b>Psikologi</b>: S/R terbentuk dari memori kolektif pelaku pasar (FOMO, takut rugi, ingin balik modal). Makin sering disentuh &amp; ditolak, makin "diakui" pasar.</li>
  </ul>

  <h4>4b. Cara Mengenali Level</h4>
  <ul>
    <li><b>Swing high / swing low (pivot/fractal)</b> — titik puncak (calon resistance) &amp; lembah (calon support) lokal. Inilah metode utama yang dipakai mesin aplikasi.</li>
    <li><b>Kekuatan = jumlah sentuhan</b>. Level yang diuji 2–3 kali lebih valid daripada yang baru sekali. Di app ditandai dengan jumlah titik (●) per zona.</li>
    <li><b>Angka bulat (round number)</b> — mis. 1.000, 5.000 sering jadi S/R psikologis.</li>
    <li><b>Konfluensi</b> — level makin kuat bila berhimpit dengan <b>SMA 20/50/200</b>, high/low 52 minggu, atau gap sebelumnya.</li>
    <li><b>Volume</b> — pantulan/penembusan yang disertai lonjakan volume jauh lebih dapat dipercaya.</li>
  </ul>

  <h4>4c. Role Reversal (Pergantian Peran)</h4>
  <p class="dim">Saat resistance <b>ditembus</b> dengan meyakinkan, ia sering <b>berubah menjadi support</b> baru saat harga kembali menguji area itu (begitu pula sebaliknya). Konsep ini mendasari strategi <b>retest</b> di bawah.</p>

  <h4>4d. Strategi Trading di S/R</h4>
  <ul>
    <li><b>Bounce / Buy at Support</b> — beli saat harga mendekati support kuat <i>dengan konfirmasi reversal</i> (mis. Hammer / Bullish Engulfing / golden cross stochastic). Stop-loss tepat di bawah support.</li>
    <li><b>Breakout (BOR/FBO)</b> — beli saat harga menembus resistance <b>diiringi volume</b>; target ke resistance berikutnya.</li>
    <li><b>Retest setelah breakout</b> — entry paling aman: tunggu harga kembali menguji ex-resistance yang kini jadi support, lalu lanjut naik (konfirmasi role reversal).</li>
    <li><b>Sell / Take Profit di Resistance</b> — kurangi posisi mendekati resistance kuat, terutama bila momentum mulai overbought.</li>
    <li><b>Hindari</b> membeli tepat di bawah resistance kuat atau menjual panik tepat di atas support.</li>
  </ul>

  <h4>4e. False Breakout (Jebakan)</h4>
  <p class="dim">Harga sesekali menembus level lalu cepat kembali (<i>fakeout</i>). Filter: butuh <b>penutupan (close)</b> di luar level — bukan sekadar sumbu — plus <b>konfirmasi volume</b>. Inilah alasan sinyal breakout app (BOR/52WBO) selalu mensyaratkan konfirmasi volume.</p>

  <h4>4f. Bagaimana Aplikasi Menghitungnya</h4>
  <ul>
    <li>Mendeteksi <b>swing-pivot</b> pada <span class="formula">SR_LOOKBACK = 60</span> candle dengan jendela <span class="formula">SR_PIVOT_WINDOW = 5</span> (<code>core/technical.py</code>).</li>
    <li>Pivot berdekatan (&lt; <span class="formula">SR_CLUSTER_TOL_PCT = 1,5%</span>) di-<b>cluster</b> menjadi satu <b>zona</b>; <b>kekuatan</b> = banyaknya pivot dalam zona.</li>
    <li>Tiap zona dilabeli relatif harga terakhir (di bawah = support, di atas = resistance) lalu diurut dari terkuat &amp; terdekat (maks <span class="formula">SR_MAX_LEVELS = 6</span>).</li>
    <li>Hasil tampil di tab <b>Analisa Saham</b>: chip zona (S/R, kekuatan ●, jarak %), narasi posisi harga, dan garis level di <b>grafik candlestick</b>.</li>
    <li>Support &amp; resistance terdekat juga memicu sinyal entry <b>BOR/FBO</b> &amp; <b>Buy on Pullback</b>, serta jadi acuan stop-loss/target di Trading Plan.</li>
  </ul>

  <h4>5. Teknik Entry (Sharp Entry)</h4>
  <ul><li><b>FBO</b> Fresh Breakout (markup) · <b>52WBO</b> Breakout 52-week high</li>
    <li><b>BOR</b> Breakout Resistance/Sideways · <b>BDTL</b> Breakout Downtrendline</li>
    <li><b>Buy on Pullback</b> · <b>Buy on Dips</b> (reversal) · <b>Gap Up</b></li></ul>
  <h4>6. Money Management & Trading Plan</h4>
  <ul><li>Hanya pakai <b>uang dingin</b>. Trading fund = 50% idle money.</li>
    <li>Loss fund = bid × 3% · Profit fund = bid × 6%.</li>
    <li>Position sizing: <span class="formula">LOT = Modal ÷ Market Price ÷ 100</span></li>
    <li><b>Taichi</b>: bagi entry OB1/OB2/OB3 (konservatif 2:4:8, moderat 30:30:40); hanya di area akumulasi/uptrend.</li>
    <li><b>RRR</b> minimal <b>1:2</b> (reward = TP−beli; risk = beli−CL).</li></ul>
  <h4>7. Stock Funnel</h4>
  <p class="dim">700+ saham BEI → 500+ Syariah (WHAT) → CAN SLIM + 6 Magic (WHY) → Teknikal (WHEN) → Money Management (HOW) → “Trade what you plan, plan what you trade”.</p>
  <h4>8. Jalur 7% — 4 Sinyal Struktur (Blueprint Jalur 7%)</h4>
  <ul><li><b>Kandang Kuda</b> (Pijakan) — area sideways tipis, candle rapat dekat MA20: menyimpan energi.</li>
    <li><b>Breaker</b> (Pendobrak) — candle body solid menembus high 20 hari + volume kuat: sinyal masuk.</li>
    <li><b>Shadow</b> (Jejak Buyer) — rejection sumbu bawah berulang di support: institusi menahan harga.</li>
    <li><b>Swing Line</b> (Ritme) — MA20 menanjak & harga konsisten di atasnya: tren sehat.</li></ul>
  <p class="dim">Konfirmasi berlapis: <b>Tren + Momentum + Volume</b> harus sepakat. Risiko maks 2%/transaksi, RRR min 1:2.
  Eksekusi di zona "Morning Boost" (09:00–09:15) / "Closing Push" (14:40–15:15); hindari noise tengah hari.</p>

  <h4>8b. Analisa Order Book (Antrean Bid-Offer) &amp; Risikonya</h4>
  <p class="dim">Sangat penting untuk memahami bahwa hanya mengandalkan pantauan antrean beli (bid) dan jual (offer) memiliki risiko nyata:</p>
  <ul>
    <li><b>1. Jebakan Fake Bid / Fake Offer (Antrean Palsu)</b>: Pemain besar/market maker sering memasang antrean beli (bid) atau jual (offer) fiktif dalam jumlah masif untuk memanipulasi psikologis ritel. Antrean ini bisa dicabut (cancel) secara tiba-tiba dalam hitungan detik sebelum transaksi benar-benar terjadi.</li>
    <li><b>2. Tidak Menunjukkan Arah Tren Sebenarnya</b>: Bid-offer hanyalah cerminan dari volatilitas dan sentimen transaksi jangka pendek (hitungan menit/jam). Indikator ini sama sekali tidak memperlihatkan tren teknikal jangka panjang (SMA 200) maupun kondisi fundamental perusahaan.</li>
    <li><b>3. Risiko Jebakan Likuiditas (Illiquid Stocks)</b>: Pada saham gorengan/lapis tiga, antrean bid-offer bisa terlihat meyakinkan, namun volume transaksi riil yang terjadi (lot yang matched) sangat sepi. Jika Anda terlanjur beli, Anda akan kesulitan menjualnya kembali tanpa harus menjatuhkan harga secara drastis.</li>
    <li><b>4. Perubahan Ekstrem Saat Pre-Closing</b>: Terkait strategi Beli Sore Jual Pagi (BSJP), antrean saham di jam pre-closing (15.50 - 16.00 WIB) bisa dimanipulasi dengan cepat. Antrean bid yang terlihat tebal di pukul 15.50 bisa lenyap seketika saat harga penutupan (closing price) terbentuk.</li>
  </ul>
  <p class="dim"><b>Pedoman Keamanan</b>: Jangan jadikan ketebalan bid-offer alasan tunggal entry. Selalu gunakan konfirmasi fundamental (6 Magic Number), filter tren utama (IHSG vs SMA200), serta volume transaksi riil yang matched.</p>

  <hr style="margin:1.6rem 0;border:none;border-top:1px solid var(--line)">
  <div class="panel-header"><h2>🧠 Landasan Teori &amp; Implementasi Teknis</h2></div>
  <p class="dim">Rujukan bagi pengguna &amp; pakar untuk meninjau dasar teori serta algoritma yang diimplementasikan. Aplikasi bersifat <b>decision-support (advisory)</b> — menganalisa &amp; memberi sinyal, tidak mengeksekusi order.</p>

  <h4>A. Arsitektur &amp; Alur Data</h4>
  <ul>
    <li>Backend <b>FastAPI</b> (Python); harga historis via <b>yfinance</b> (sufiks <i>.JK</i> utk BEI) + curl_cffi; antarmuka Jinja2 + JavaScript.</li>
    <li>Sumber fundamental utama: <b>master_data_syariah.csv</b> (75 saham DES terkurasi — EPS QnQ, ROA, ROE, NPM, PER, PBV, DER, PEG, BVPS, MP, Free Float, Dividend Yield), lebih andal utk IDX dibanding yfinance murni.</li>
    <li>Alur <b>Stock Funnel</b>: Universe Syariah (WHAT) → Fundamental 6 Magic + CAN SLIM (WHY) → Teknikal + Jalur 7% (WHEN) → Money Management (HOW).</li>
    <li>Modul inti dipakai <b>konsisten lintas-tab</b>: funnel, undervalue, decisions, accounts (MM), portfolio, roi, bei_calendar.</li>
  </ul>

  <h4>B. Screening Syariah (DSN-MUI + AAOIFI)</h4>
  <ul>
    <li><b>DSN-MUI</b> No. 40/2003 &amp; 80/2011: terdaftar <b>DES/ISSI</b> (OJK), usaha halal; utang berbunga ÷ aset ≤ <b>45%</b>; pendapatan non-halal ÷ total ≤ <b>10%</b>; transaksi tunai &amp; long-only.</li>
    <li><b>AAOIFI</b> (pelengkap): utang ÷ kapitalisasi ≤ 30%; kas+piutang ÷ kapitalisasi ≤ 30%; pendapatan non-halal ≤ 5%.</li>
    <li><i>compliant</i> = terdaftar DES <b>DAN</b> bukan HARAM/NON-COMPLIANT; status ambigu → "needs manual check" (ditandai ⚠).</li>
  </ul>

  <h4>C. Mesin Fundamental</h4>
  <p><b>6 Magic Number</b> (skor 0–6): EPS QnQ ≥ 25% · ROA &gt; 15% · ROE &gt; 15% · DER &lt; 100% · PBV &lt; 1 · PER &lt; 10×; bonus Dividend Yield &gt; 7% + nilai intrinsik.</p>
  <p><b>CAN SLIM</b> (skor 0–7): <b>C</b> EPS QnQ ≥ 25% (sumber sama 6 Magic: TV/hybrid) · <b>A</b> pertumbuhan tahunan/YoY ≥ 20% &amp; ROE ≥ 17% · <b>N</b> harga ≥ 85% high-52-pekan · <b>S</b> free-float &lt; 50% &amp; (volume ≥ 1,5× atau FF &lt; 25%) · <b>L</b> peringkat ≤ 3 di sektor atau RS 6 bulan &gt; indeks · <b>I</b> institusi ≥ 1% · <b>M</b> IHSG vs SMA50.</p>

  <h4>D. Mesin Teknikal &amp; Jalur 7%</h4>
  <ul>
    <li>Indikator: SMA 20/50/200, RSI(14), Stochastic %K/%D, MACD (EMA 12/26/9), Support/Resistance, deteksi candlestick.</li>
    <li>Sinyal O'Neil: RSI + MACD + MA-cross → BUY/HOLD/SELL (skor −3..+3), ma_cross GOLDEN/DEATH.</li>
    <li><b>Jalur 7%</b> — 4 sinyal struktur: Kandang Kuda, Breaker, Shadow, Swing Line; konfirmasi berlapis Tren + Momentum + Volume.</li>
  </ul>

  <h4>E. Skor Funnel (verdict Analisa &amp; Screening)</h4>
  <p class="formula">skor = (6Magic÷6 × 0,35 + CANSLIM÷7 × 0,35 + teknikal × 0,15 + Jalur7 × 0,15) × 100</p>
  <p class="dim">Skor 0–100 ini ditampilkan &amp; diurutkan di tab Analisa Saham dan Screening, lalu <b>dipakai ulang</b> oleh Pusat Keputusan (menjamin konsistensi lintas-tab).</p>

  <h4>F. Screener Undervalue (multi-faktor + backtest historis)</h4>
  <ul>
    <li><b>Valuasi (50%)</b>: kemurahan (PBV, PER, PEG, Margin of Safety via angka Graham = √(22,5 × EPS × BVPS)) + kualitas (ROE, DER, pertumbuhan EPS) + dividen.</li>
    <li><b>Timing (20%)</b>: RSI oversold, posisi vs 52-pekan, jarak ke SMA200, momentum 20 hari.</li>
    <li><b>Backtest (30%)</b>: simulasi entry mean-reversion (RSI &lt; 35) sepanjang 2 thn → <b>win-rate</b> &amp; rata-rata return horizon ~1 bulan; dikoreksi ukuran sampel (<i>anti value-trap</i>: "murah tapi tak terbukti" dihukum).</li>
    <li>Hanya saham syariah; tiap kandidat diberi rencana trading (entry/stop/target/RRR).</li>
  </ul>

  <h4>G. Pusat Keputusan — Skor Keyakinan Gabungan</h4>
  <p class="formula">conviction = (0,40 × skorFunnel÷100 + 0,30 × skorUndervalue÷100 + 0,30 × akurasiBacktest÷100) × 100</p>
  <p class="dim">Menyatukan output ketiga tab. <b>Top-5 &amp; kolom BELI diurut skor ini</b> (selaras). Tingkat: ≥55 kuat · 45–54 sedang · &lt;45 lemah.</p>

  <h4>H. Strategi N-Emiten Per-RDN</h4>
  <ul>
    <li>Portofolio dijaga tepat <b>N emiten</b> (default 3) <b>per RDN/broker</b> (tiap broker dikelola terpisah karena skema biaya berbeda).</li>
    <li>Kurang dari N → <b>BELI</b> isi slot (kandidat terkuat yang punya cash). Lebih → <b>JUAL</b> emiten terlemah (pangkas). Penuh → <b>ROTASI</b> bila kandidat jauh lebih kuat (selisih conviction ≥ ambang).</li>
    <li>Eksit wajib lebih dulu: <b>CUT LOSS</b> P/L ≤ −7% (Jalur 7%), <b>TAKE PROFIT</b> ≥ +20%, fundamental AVOID.</li>
    <li><b>Trading US hanya di Pluang</b> (USD, 1 lembar = 1 unit). RDN BEI (mis. Profits Anywhere) hanya untuk saham IDX. Nilai BUY/SELL selalu mengikuti lot &amp; cash portofolio aktual.</li>
  </ul>

  <h4>I. Money Management &amp; Biaya Transaksi (per-RDN)</h4>
  <ul>
    <li>Hanya uang dingin. Dana trading = 50% cash; bid/emiten = dana trading ÷ N.</li>
    <li>Loss fund = bid × risk% (maks 5%); profit fund = bid × profit% (min 2× risk; default 6%).</li>
    <li><b>Biaya per-RDN</b> (mis. beli 0,15% / jual 0,25%) masuk hitungan: lot agar (harga×lembar + biaya beli) muat dalam bid; target jual <b>net</b> = profit% + biaya pulang-pergi.</li>
    <li>Status portofolio memakai <b>P/L bersih</b> (setelah biaya) + <b>harga impas</b>: <span class="formula">impas = modalRiil ÷ (lembar × (1 − biayaJual%))</span></li>
  </ul>

  <h4>J. ROI Integral &amp; Strategi Adaptif (AI ← ROI)</h4>
  <ul>
    <li><b>ROI Integral Portofolio</b>: Imbal hasil menyeluruh yang menggabungkan transaksi tertutup (<i>Realized</i>) dan posisi berjalan (<i>Unrealized</i>):
      <br>
      <span class="formula">ROI Integral = (P/L Bersih Realized + Unrealized) ÷ Total Modal Terinvestasi × 100%</span>
      <br>
      • <i>Unrealized</i>: Menggunakan modal posisi aktif (termasuk biaya beli) dan estimasi P/L bersih (dikurangi estimasi biaya jual).
      <br>
      • <i>Realized</i>: Menggunakan akumulasi modal historis dan laba/rugi bersih nyata yang terkumpul dari jurnal transaksi tertutup.
      <br>
      Metode ini mencegah bias performa jangka pendek dan memberikan visualisasi <b>equity curve</b> yang utuh dan akurat.
    </li>
    <li>Bila ROI realized &lt; target (6%) → <b>ambang akurasi BELI dinaikkan</b> sebanding gap (lebih selektif) untuk mengejar target; win-rate &lt; 50% → diperketat lagi. Loop pembelajaran transparan &amp; dapat diaudit.</li>
  </ul>

  <h4>K. Kesadaran Bursa &amp; Mode Uji</h4>
  <ul>
    <li><b>Kalender libur BEI</b> resmi + akhir pekan + deteksi data basi → status bursa buka/tutup. Saat tutup, sinyal teknikal &amp; average-down ditahan jadi HOLD (ditandai); eksit keras tetap direncanakan utk sesi buka.</li>
    <li><b>Mode Uji</b>: paksa sinyal penuh walau libur (utk pengembangan / aliran data).</li>
  </ul>

  <h4>L. Impor Data (OCR lokal, deterministik)</h4>
  <ul>
    <li><b>Tesseract OCR + pdfplumber</b> (tanpa LLM) — tidak mengarang angka. Parser dwi-format angka (Indonesia "2.100" &amp; internasional "2,730.00").</li>
    <li>Format didukung: holdings <b>Phintraco/Profits Anywhere</b>, <b>Trade Confirmation</b>, &amp; <b>Riwayat Transaksi (Order History)</b> — BUY↔JUAL dicocokkan <b>FIFO</b> → ROI nyata ke jurnal, posisi terbuka, &amp; saldo cash.</li>
  </ul>

  <h4>M. Referensi Teori</h4>
  <ul>
    <li><i>Sharia Investment and Trading Module</i> (Doddy Eka Putra / YLive Academy) — funnel, 6 Magic, Jalur 7%, MM/Taichi/RRR.</li>
    <li>William J. O'Neil, <i>How to Make Money in Stocks</i> — metodologi CAN SLIM.</li>
    <li>Fatwa DSN-MUI No. 40/DSN-MUI/X/2003 &amp; No. 80/DSN-MUI/III/2011; kriteria DES (OJK); standar <b>AAOIFI</b>.</li>
    <li>Analisa teknikal klasik (Wyckoff, J. Murphy): SMA, RSI, MACD, Stochastic, S/R, candlestick.</li>
  </ul>

  <h4>N. Batasan &amp; Disclaimer</h4>
  <ul>
    <li><b>Advisory only</b> — bukan ajakan/eksekusi jual-beli; keputusan &amp; risiko sepenuhnya pada pengguna.</li>
    <li>Backtest = peluang historis, <b>bukan jaminan</b> masa depan; fundamental snapshot (master) + harga yfinance bisa beda dari realtime broker.</li>
    <li>Seluruh transaksi <b>tunai, long-only, non-margin</b> — sesuai kaidah syariah.</li>
  </ul>

  <h4>O. Integrasi Saham Syariah &amp; Emas Digital (Tring Pegadaian)</h4>
  <p class="dim">Panduan operasional rotasi aset dinamis untuk mendongkrak ROI keseluruhan portofolio Anda:</p>
  <ul>
    <li><b>IHSG Uptrend (Bullish)</b>: Cairkan saldo emas digital di <b>Tring Pegadaian</b> secara instan, lalu transfer hasil penjualan (cair T+0) ke RDN <b>Profits Anywhere</b> untuk mengeksekusi sinyal BELI saham syariah potensial.</li>
    <li><b>IHSG Downtrend (Bearish)</b>: Amankan 60% dari Dana Cadangan (<i>Reserve Fund</i>) Anda ke <b>Emas Digital Tring Pegadaian</b>. Emas menjaga nilai aset dari devaluasi Rupiah selagi pasar saham sedang lesu.</li>
    <li><b>Aturan Rotasi Ekstrem (ROI Booster)</b>:
      <br>• <i>Jual Emas ke Saham</i>: Saat emas mendekati harga tertinggi dan saham berfundamental kokoh (6 Magic Number) jatuh ke support kuat (Stochastic oversold &lt; 20).
      <br>• <i>Jual Saham ke Emas</i>: Saat target untung saham tercapai (+6% s.d +10% net) dan Stochastic jenuh beli (&gt; 80), amankan profit Anda dengan membelikan emas digital.
    </li>
  </ul>

  <h4>P. Kajian Pengelolaan Uang Dingin (Reserve Fund)</h4>
  <p class="dim">Analisis penempatan dana dingin standby agar tidak tergerus inflasi Rupiah dengan likuiditas tinggi:</p>
  <ul>
    <li><b>Kepatuhan Syariah</b>: Emas Digital <b>100% Syariah</b> sesuai <b>Fatwa DSN-MUI No. 77/2010</b>. USD Digital / Stablecoin (USDT/USDC) statusnya masih abu-abu/debatable dalam fiqih kontemporer.</li>
    <li><b>Spread &amp; Likuiditas</b>: Emas memiliki spread 3-4%, namun Tring Pegadaian sangat likuid (cair instan ke bank pribadi). Batasi pencairan hanya untuk rotasi taktis jangka menengah (bukan harian).</li>
    <li><b>Strategi Hybrid (60/40)</b>: Bagi Dana Cadangan menjadi:
      <br>• <b>60% Emas Digital</b> (Lindung Nilai Jangka Panjang, dicairkan hanya saat pasar crash untuk serok bawah).
      <br>• <b>40% Kas RDN / RDPU Syariah</b> (Likuiditas tempur harian tanpa spread, siap deploy seketika sinyal entry muncul).
    </li>
  </ul>

  <h4>Q. Proteksi Likuiditas &amp; Anti-Saham Gorengan</h4>
  <p class="dim">Aturan dan tembok pertahanan otomatis sistem untuk menghindari jebakan saham spekulatif (gorengan) yang tidak likuid:</p>
  <ul>
    <li><b>Filter Universe Awal</b>: Pemindaian hanya dilakukan pada 75 saham syariah pilihan utama terkurasi (komponen JII/IDX80/LQ45) pada database <i>master_data_syariah.csv</i>. Saham gorengan lapis ketiga (micro-cap) secara otomatis diabaikan sejak awal.</li>
    <li><b>Filter Fundamental (Anti-Avoid)</b>: Kriteria 6 Magic Numbers dan CAN SLIM memblokir saham berkinerja buruk (rugi bersih, utang terlalu tinggi) dengan label <b>AVOID</b>. Saham berlabel AVOID tidak akan pernah direkomendasikan beli walau harganya melonjak naik.</li>
    <li><b>Deteksi Risiko Likuiditas (Volume Rata-Rata)</b>: Sistem memantau volume harian rata-rata 20 hari terakhir (MA20 Volume):
      <br>• <i>Illiquid (Risiko Sangat Tinggi)</i>: Rata-rata &lt; 500.000 lembar (~5.000 lot/hari). <b>Hard gate</b> — digugurkan dari kandidat BELI.
      <br>• <i>Likuiditas Rendah (Sangat Likuid)</i>: Rata-rata &ge; 2.000.000 lembar (~20.000 lot/hari). Sangat direkomendasikan untuk keamanan eksekusi masuk &amp; keluar.
    </li>
    <li><b>Validasi Volume Spike</b>: Sinyal breakout harga (tembus resistance/52-weeks high) wajib dikonfirmasi oleh volume spike &gt; 1.5x rata-rata untuk menyaring pompa harga palsu (*false breakout*) yang dimanipulasi sepihak pada saham gorengan.</li>
  </ul>

  <h4>Q2. Scoring Rekomendasi (Hard Gate → Quality → Timing → Final)</h4>
  <p class="dim">Model skor Funnel default (<code>SCORING_MODEL=layered</code>). Rollback ke lama: set <code>SCORING_MODEL=legacy</code> di <code>.env</code>.</p>
  <ul>
    <li><b>Hard Gate</b> (satu FAIL = skip): DES/ISSI → spread ≤2% &amp; vol median 5 hari ≥ Rp5jt → IHSG bukan downtrend ekstrem (MA20 &lt; MA60 by &gt;5%).</li>
    <li><b>Quality Score 0–100+</b>: <code>Fund×0.3 + Tech×0.2 + Bandar×0.15 + Liq×0.15 + IHSG×0.15 + Risk×0.1</code> (bobot spreadsheet, jumlah 105%).</li>
    <li><b>Timing Score</b> (terpisah): RSI zona, volume spike &gt;2×, gap, support/MA — layak entry bila ≥65 (filter, bukan penambah Final).</li>
    <li><b>Regime Multiplier</b>: BULLISH ×1.0 · NEUTRAL ×0.8 · BEARISH ×0 (×0.5 bila saham defensif &amp; bukan ekstrem). Regime dari MA20 vs MA60 indeks.</li>
    <li><b>Final = Quality × Multiplier + Timing Bonus (0)</b>: ≥75 STRONG BUY · 55–74 WATCHLIST · &lt;55 SKIP. Eligible BELI penuh hanya STRONG BUY + timing layak.</li>
  </ul>

  <h4>R. Sumber Data &amp; Caching Timing</h4>
  <p class="dim">Informasi mengenai asal usul data dan siklus pembaruan untuk setiap analisis di dalam sistem:</p>
  <ul>
    <li><b>Analisis Teknikal &amp; Grafik Candlestick</b>: Data harga penutupan, volume transaksi, dan histori grafik ditarik langsung dari <b>Yahoo Finance API (Real-Time/Intraday)</b>. Sistem menerapkan cache agresif selama <b>10 menit</b> (Cache TTL = 600 detik) untuk menghemat kuota jaringan dan memastikan data tetap segar selama sesi perdagangan berjalan.</li>
    <li><b>Analisis Fundamental (6 Magic &amp; CAN SLIM)</b>: Data metrik rasio keuangan bersumber utama dari database lokal terkurasi <b>master_data_syariah.csv</b> (diperbarui berkala setelah rilis laporan keuangan resmi kuartal Q1, Q2, Q3, dan Tahunan emiten di Bursa Efek Indonesia) dengan fallback otomatis ke Yahoo Finance jika data lokal tidak ditemukan.</li>
    <li><b>Arah Pasar (IHSG)</b>: Tren IHSG ditentukan oleh pergerakan indeks <b>^JKSE</b> secara harian dari Yahoo Finance untuk memandu porsi alokasi kas secara defensif/agresif.</li>
  </ul>`;
}

/* ===================== PORTOFOLIO ===================== */
async function loadPortfolio(){
  $('#port-table').innerHTML='<div class="empty"><span class="spin"></span> Memuat harga…</div>';
  try{ const d=await api('/api/portfolio'); const s=d.summary;
    window._portfolioData = d;
    $('#port-summary').innerHTML=`${miniStat('Total Nilai',fmt(s.total_value),s.jumlah_posisi+' posisi')}
      ${plStat('P/L Bersih',s.total_net_pl)}${plStat('Return Bersih',s.total_net_pl_pct,true)}`;
    
    const trading_ps = d.positions.filter(p => (p.type || 'trading') === 'trading');
    const investasi_ps = d.positions.filter(p => p.type === 'investasi');
    
    function renderTable(ps, title, summary) {
      let h = `<h3 class="sec" style="margin: 1.5rem 0 .5rem; border-bottom: 1px solid var(--line); padding-bottom: .4rem; display: flex; justify-content: space-between; align-items: center;">
        <span>📊 ${title}</span>
        <span style="font-size: .8rem; font-weight: normal; color: var(--mute);">
          Modal: <b>Rp ${fmt(summary.total_modal)}</b> · pasar: <b>Rp ${fmt(summary.total_value)}</b> · P/L: <b class="${summary.total_pl>=0?'pl-up':'pl-down'}">${summary.total_pl>=0?'+':''}Rp ${fmt(Math.abs(summary.total_pl))} (${summary.total_pl_pct>=0?'+':''}${summary.total_pl_pct}%)</b>
        </span>
      </h3>`;
      if (!ps.length) {
        h += '<div class="empty" style="padding: 1rem 0;">Belum ada posisi di portfolio ini.</div>';
        return h;
      }
      h += '<table><thead><tr><th>Kode</th><th>Lot / Lembar (US)</th><th style="text-align:right">Avg</th><th style="text-align:right" title="harga impas setelah biaya beli+jual">Impas</th><th style="text-align:right">Harga</th><th style="text-align:right" title="nilai pasar kotor → hasil bersih bila dijual (stlh fee jual)">Nilai (kotor → jual bersih)</th><th style="text-align:right" title="setelah biaya beli & jual">P/L Bersih</th><th></th></tr></thead><tbody>';
      ps.forEach(p => { 
        const isUSD = p.currency === 'USD';
        const cSymbol = isUSD ? '$' : 'Rp ';
        const cFmt = val => {
          if (val === null || val === undefined || val === '') return '—';
          return isUSD ? Number(val).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : Number(val).toLocaleString('id-ID');
        };
        const up=(p.net_pl||0)>=0; 
        const beUp=p.current_price>=p.break_even;
        h += `<tr><td><span class="tkr">${p.ticker}</span> ${p.syariah?'<span class="badge buy" style="font-size:.6rem">✓</span>':'<span class="badge sell" style="font-size:.6rem">non</span>'}${p.broker?` <span class="badge na" style="font-size:.55rem" title="fee beli ${p.fee_buy_pct}% / jual ${p.fee_sell_pct}%">${esc(p.broker)}</span>`:''}</td>
          <td class="num">${p.lots} <span class="mut" style="font-size:.65rem">${isUSD?'sh':'lot'}</span></td>
          <td style="text-align:right" class="num">${cSymbol}${cFmt(p.avg_price)}</td>
          <td style="text-align:right" class="num ${beUp?'pl-up':'pl-down'}" title="impas (sudah hitung biaya)">${cSymbol}${cFmt(p.break_even)}</td>
          <td style="text-align:right" class="num">${cSymbol}${cFmt(p.current_price)}</td>
          <td style="text-align:right" class="num">${cSymbol}${cFmt(p.value)}<br><span class="mut" style="font-size:.62rem" title="hasil bersih bila dijual semua kini (stlh fee jual ${p.fee_sell_pct}%)">jual ≈ <b style="color:var(--buy)">${cSymbol}${cFmt(p.net_value)}</b></span></td>
          <td style="text-align:right" class="num ${up?'pl-up':'pl-down'}"><b>${p.net_pl>=0?'+':''}${cSymbol}${cFmt(Math.abs(p.net_pl))}</b><br><span style="font-size:.72rem">${p.net_pl_pct>=0?'+':''}${p.net_pl_pct}%</span><br><span class="mut" style="font-size:.62rem" title="P/L kotor (harga saja)">kotor ${p.pl>=0?'+':''}${cSymbol}${cFmt(Math.abs(p.pl))}</span></td>
          <td style="text-align:right;white-space:nowrap"><button class="btn ghost" style="padding:.2rem .5rem;font-size:.7rem" onclick="openSell(${p.id},'${p.ticker}',${p.lots},${p.current_price||p.avg_price},${p.fee_sell_pct||0.25})" title="Jual (sebagian/penuh) & sinkron">💰 Jual</button>
            <button class="del-btn" onclick="delPosition(${p.id})" title="Hapus tanpa catat">🗑</button></td></tr>`;
      });
      h += '</tbody></table>';
      return h;
    }
    
    let htmlContent = renderTable(trading_ps, 'Portofolio Trading Harian', d.trading_summary || {total_modal:0,total_value:0,total_pl:0,total_pl_pct:0});
    htmlContent += renderTable(investasi_ps, 'Portofolio Investasi Saham (Tahunan)', d.investasi_summary || {total_modal:0,total_value:0,total_pl:0,total_pl_pct:0});
    
    $('#port-table').innerHTML = htmlContent;
  }catch(e){ $('#port-table').innerHTML='<div class="empty">Gagal memuat.</div>'; }
  loadRDN(); loadROI();
}
async function loadInvestasiSaham() {
  $('#inv-summary-cards').innerHTML = '<div class="empty"><span class="spin"></span> Memuat ringkasan…</div>';
  $('#inv-port-table-container').innerHTML = '<div class="empty"><span class="spin"></span> Memuat portofolio…</div>';
  $('#inv-recs-container').innerHTML = '<div class="empty"><span class="spin"></span> Memuat analisis…</div>';

  try {
    const d = await api('/api/portfolio/investasi-info');
    const s = d.summary;
    
    // 1. Render Summary Cards
    const plClass = s.total_pl >= 0 ? 'pl-up' : 'pl-down';
    $('#inv-summary-cards').innerHTML = `
      <div class="cardlet">
        <div class="lbl mut" style="font-size:.7rem">TOTAL MODAL INVESTASI</div>
        <div class="num" style="font-size:1.4rem;font-weight:800">${fmt(s.total_modal)}</div>
        <div class="mut" style="font-size:.7rem">Biaya beli termasuk</div>
      </div>
      <div class="cardlet">
        <div class="lbl mut" style="font-size:.7rem">NILAI PASAR &amp; RETURN</div>
        <div class="num ${plClass}" style="font-size:1.4rem;font-weight:800">${fmt(s.total_value)}</div>
        <div class="mut ${plClass}" style="font-size:.7rem">
          P/L Bersih: <b>${s.total_pl >= 0 ? '+' : ''}${fmt(s.total_pl)} (${s.total_pl_pct >= 0 ? '+' : ''}${s.total_pl_pct}%)</b>
        </div>
      </div>
      <div class="cardlet" style="border-color: var(--brand-2)">
        <div class="lbl mut" style="font-size:.7rem;color: var(--brand-2)">PROYEKSI DIVIDEN MENDATANG</div>
        <div class="num" style="font-size:1.4rem;font-weight:800;color: var(--buy)">${fmt(s.total_expected_dividends)}</div>
        <div class="mut" style="font-size:.7rem">Berdasarkan porsi lot saat ini</div>
      </div>
    `;

    // 2. Render Portfolio Table
    let tableHtml = '';
    if (!d.positions.length) {
      tableHtml = '<div class="empty" style="padding: 1.5rem 0;">Belum ada posisi investasi. Tambahkan posisi bertipe "Investasi Saham" di tab Portofolio.</div>';
    } else {
      tableHtml = `<table>
        <thead>
          <tr>
            <th>Kode</th>
            <th>Lot</th>
            <th style="text-align:right">Harga Avg</th>
            <th style="text-align:right">Impas</th>
            <th style="text-align:right">Harga Live</th>
            <th style="text-align:right">Nilai Bersih</th>
            <th style="text-align:right">P/L Bersih</th>
            <th style="text-align:right">Proyeksi Dividen</th>
          </tr>
        </thead>
        <tbody>`;
      d.positions.forEach(p => {
        const up = (p.net_pl || 0) >= 0;
        const beUp = p.current_price >= p.break_even;
        // Cari info dividen untuk posisi ini dari recommendations
        const rec = d.recommendations.find(r => r.ticker === p.ticker);
        const expDiv = rec ? rec.expected_dividend_idr : 0;
        const divInfo = rec && rec.dividend && rec.dividend.upcoming && rec.dividend.upcoming.expected
          ? `Rp ${fmt(rec.dividend.upcoming.amount)} / lbr <br><span class="mut" style="font-size:.62rem">Ex-Date: ${rec.dividend.upcoming.ex_date}</span>`
          : '<span class="mut">-</span>';
          
        tableHtml += `<tr>
          <td><span class="tkr">${p.ticker}</span> ${p.syariah ? '<span class="badge buy" style="font-size:.6rem">✓</span>' : '<span class="badge sell" style="font-size:.6rem">non</span>'}</td>
          <td class="num">${p.lots}</td>
          <td style="text-align:right" class="num">${fmt(p.avg_price)}</td>
          <td style="text-align:right" class="num ${beUp ? 'pl-up' : 'pl-down'}">${fmt(p.break_even)}</td>
          <td style="text-align:right" class="num">${fmt(p.current_price)}</td>
          <td style="text-align:right" class="num"><b>${fmt(p.net_value)}</b></td>
          <td style="text-align:right" class="num ${up ? 'pl-up' : 'pl-down'}">
            <b>${p.net_pl >= 0 ? '+' : ''}${fmt(p.net_pl)}</b><br>
            <span style="font-size:.72rem">${p.net_pl_pct >= 0 ? '+' : ''}${p.net_pl_pct}%</span>
          </td>
          <td style="text-align:right" class="num" style="color:var(--buy)">
            <b>${expDiv > 0 ? '+' + fmt(expDiv) : '0'}</b><br>
            <span style="font-size:.65rem;color:var(--mute)">${divInfo}</span>
          </td>
        </tr>`;
      });
      tableHtml += '</tbody></table>';
    }
    $('#inv-port-table-container').innerHTML = tableHtml;

    // 3. Render Recommendation Cards
    let recsHtml = '';
    d.recommendations.forEach(r => {
      const ev = r.evaluation;
      const div = r.dividend;
      if (!ev) {
        recsHtml += `
          <div class="cardlet" style="padding:1rem;display:flex;flex-direction:column;gap:.5rem">
            <div class="between">
              <h3><span class="tkr">${r.ticker}</span></h3>
              <span class="badge sell">Tidak Ada Data</span>
            </div>
            <p class="mut" style="font-size:.78rem">Saham tidak ditemukan dalam master data syariah lokal.</p>
          </div>
        `;
        return;
      }
      
      const verdClass = ev.css === 'buy' ? 'buy' : ev.css === 'warning' ? 'warning' : 'sell';
      const scoreC = ev.valuation_score >= 55 ? 'pl-up' : 'pl-down';
      const timeC = (ev.timing_score || 0) >= 50 ? 'pl-up' : 'pl-down';
      
      // Proyeksi dividen yang diumumkan atau diestimasi
      let upcomingHtml = '<span class="mut">Tidak ada dalam waktu dekat</span>';
      if (div && div.upcoming && div.upcoming.expected) {
        const upDiv = div.upcoming;
        upcomingHtml = `
          <div style="font-size:.8rem;line-height:1.4">
            <div>Nominal: <b style="color:var(--buy)">Rp ${fmt(upDiv.amount)} / lembar</b></div>
            <div>Ex-Date: <b>${upDiv.ex_date}</b> <span class="badge na" style="font-size:.6rem;padding:.15rem .3rem">${upDiv.source}</span></div>
            <div>Imbal Hasil Event: <b>${upDiv.event_yield_pct}%</b></div>
            <div>Waktu: <b style="color:var(--brand-2)">${upDiv.days_until} hari lagi</b></div>
          </div>
        `;
      }

      // Rincian faktor fundamental/valuasi
      let factorsHtml = '';
      if (ev.factors) {
        factorsHtml = '<table style="width:100%;font-size:.74rem;margin-top:.4rem;border-collapse:collapse">';
        ev.factors.forEach(f => {
          const valPct = f.nilai01 != null ? Math.round(f.nilai01 * 100) : null;
          const scoreColor = valPct == null ? 'var(--mute)' : valPct >= 70 ? 'var(--buy)' : valPct >= 40 ? 'var(--hold)' : 'var(--sell)';
          factorsHtml += `
            <tr style="border-bottom:1px solid rgba(255,255,255,.03)">
              <td class="mut" style="padding:.2rem 0">${f.faktor}</td>
              <td style="text-align:right;padding:.2rem 0;font-weight:700;color:${scoreColor}">${valPct != null ? valPct + '%' : '-'}</td>
            </tr>`;
        });
        factorsHtml += '</table>';
      }

      // Rincian faktor timing teknikal
      let timingHtml = '';
      if (ev.timing) {
        const t = ev.timing;
        timingHtml = `
          <div style="display:flex;flex-wrap:wrap;gap:.6rem;margin-top:.5rem">
            <span class="badge na" style="font-size:.7rem">RSI: <b>${t.rsi}</b></span>
            <span class="badge na" style="font-size:.7rem">Jarak SMA200: <b>${t.dist_sma200_pct}%</b></span>
            <span class="badge na" style="font-size:.7rem">Posisi 52w: <b>${t.pos_52w_pct}%</b></span>
            <span class="badge na" style="font-size:.7rem">Momentum 20h: <b>${t.momentum_20d_pct}%</b></span>
          </div>
        `;
      }

      // Rencana Trading (Trading Plan)
      const tp = ev.plan || {};
      const tp_html = tp.entry ? `
        <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:.4rem;background:rgba(255,255,255,0.03);padding:.5rem;border-radius:6px;font-size:.74rem;margin-top:.6rem;text-align:center">
          <div><div class="mut" style="font-size:.65rem">Entry Limit</div><b>${fmt(tp.entry)}</b></div>
          <div><div class="mut" style="font-size:.65rem">Target Keluar</div><b>${fmt(tp.target)}</b></div>
          <div><div class="mut" style="font-size:.65rem">Stop Loss</div><b>${fmt(tp.stop_loss)}</b></div>
        </div>
        <div style="font-size:.7rem;margin-top:.3rem" class="mut text-center">Risk: <b>${tp.risk_pct}%</b> · Reward: <b>${tp.reward_pct}%</b> · RRR: <b>${tp.rrr}</b></div>
      ` : '<div class="mut" style="font-size:.74rem;margin-top:.5rem">Trading plan tidak tersedia.</div>';

      const divYield = (div && div.dividend_yield != null) ? fmt(div.dividend_yield) : '-';
      const divStreak = div ? (div.pay_streak || div.years_paid || 0) : 0;

      recsHtml += `
        <div class="cardlet" style="padding:1.2rem;display:flex;flex-direction:column;gap:.6rem;border-top:3px solid ${ev.css === 'buy' ? 'var(--buy)' : ev.css === 'warning' ? 'var(--hold)' : 'var(--line)'}">
          <div class="between" style="align-items:flex-start">
            <div>
              <h3 style="margin:0"><span class="tkr">${r.ticker}</span> <span class="badge buy" style="font-size:.65rem">✓ Syariah</span></h3>
              <div class="mut" style="font-size:.7rem;margin-top:.1rem">Yield Tahunan: <b>${divYield}%</b> · Streak: <b>${divStreak} tahun</b></div>
            </div>
            <span class="badge ${verdClass}" style="font-size:.85rem;padding:.3rem .6rem">${ev.label}</span>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:.8rem;margin-top:.3rem">
            <div>
              <div class="mut" style="font-size:.7rem">SKOR VALUASI FUNDAMENTAL</div>
              <div style="font-size:1.3rem;font-weight:800" class="${scoreC}">${ev.valuation_score != null ? Math.round(ev.valuation_score) : '-'}<span style="font-size:.78rem;color:var(--mute)">/100</span></div>
              ${factorsHtml}
              <div style="font-size:.72rem;margin-top:.4rem" class="mut">
                Harga Graham: <b>${ev.valuation_extra && ev.valuation_extra.graham_number != null ? fmt(ev.valuation_extra.graham_number) : '-'}</b><br>
                Margin of Safety: <b class="${ev.valuation_extra && ev.valuation_extra.margin_of_safety_pct >= 0 ? 'pl-up' : 'pl-down'}">${ev.valuation_extra && ev.valuation_extra.margin_of_safety_pct != null ? ev.valuation_extra.margin_of_safety_pct + '%' : '-'}</b>
              </div>
            </div>
            <div>
              <div class="mut" style="font-size:.7rem">SKOR TIMING TEKNIKAL</div>
              <div style="font-size:1.3rem;font-weight:800" class="${timeC}">${ev.timing_score != null ? Math.round(ev.timing_score) : '-'}<span style="font-size:.78rem;color:var(--mute)">/100</span></div>
              ${timingHtml}
              <div style="margin-top:.6rem;border-top:1px solid rgba(255,255,255,.03);padding-top:.4rem">
                <div class="mut" style="font-size:.7rem;text-transform:uppercase;font-weight:700;color:var(--brand-2)">Dividen Mendatang</div>
                ${upcomingHtml}
              </div>
            </div>
          </div>

          <div style="margin-top:.4rem;border-top:1px solid rgba(255,255,255,.03);padding-top:.5rem">
            <div class="mut" style="font-size:.7rem;text-transform:uppercase;font-weight:700">Rencana Pembelian &amp; Risiko</div>
            ${tp_html}
          </div>
        </div>
      `;
    });
    $('#inv-recs-container').innerHTML = recsHtml;

  } catch (e) {
    console.error(e);
    $('#inv-summary-cards').innerHTML = '<div class="empty">Gagal memuat ringkasan.</div>';
    $('#inv-port-table-container').innerHTML = '<div class="empty">Gagal memuat portofolio.</div>';
    $('#inv-recs-container').innerHTML = '<div class="empty">Gagal memuat rekomendasi.</div>';
  }
}
async function loadROI(){
  try{ const d=await api('/api/portfolio/roi'); const I=d.integral, U=d.unrealized, R=d.realized, a=d.adaptive;
    const ok=d.on_track, roiC=I.roi_pct>=0?'pl-up':'pl-down';
    const prog=Math.max(0,Math.min(100, (I.roi_pct/d.target_pct)*100));
    let h=`<div class="grid g-3" style="gap:.8rem;margin-top:.5rem">
      <div class="cardlet"><div class="lbl mut" style="font-size:.7rem">ROI INTEGRAL (realized+unrealized)</div>
        <div class="num ${roiC}" style="font-size:1.5rem;font-weight:800">${I.roi_pct>=0?'+':''}${I.roi_pct}%</div>
        <div class="mut" style="font-size:.7rem">${fmt(I.pl)} dari modal ${fmt(I.invested)}</div></div>
      <div class="cardlet"><div class="lbl mut" style="font-size:.7rem">REALIZED (${R.n_trades} trade)</div>
        <div class="num ${(R.roi_pct||0)>=0?'pl-up':'pl-down'}" style="font-size:1.3rem;font-weight:800">${R.roi_pct==null?'–':(R.roi_pct>=0?'+':'')+R.roi_pct+'%'}</div>
        <div class="mut" style="font-size:.7rem">win ${R.win_rate??'–'}% · avg ${R.avg_roi??'–'}%</div></div>
      <div class="cardlet"><div class="lbl mut" style="font-size:.7rem">UNREALIZED (terbuka)</div>
        <div class="num ${(U.roi_pct||0)>=0?'pl-up':'pl-down'}" style="font-size:1.3rem;font-weight:800">${U.roi_pct>=0?'+':''}${U.roi_pct}%</div>
        <div class="mut" style="font-size:.7rem">${fmt(U.pl)}</div></div></div>`;
    h+=`<div style="margin-top:.7rem"><div class="between" style="font-size:.78rem"><span>Progres ke target <b>${d.target_pct}%</b></span>
      <span class="${ok?'pl-up':'pl-down'}">${ok?'✓ on-track':'gap '+d.gap_to_target+'%'}</span></div>
      <div class="bar" style="height:9px;margin-top:.3rem"><i style="width:${prog}%;background:${ok?'var(--buy)':'var(--brand-2)'}"></i></div></div>`;
    h+=`<div style="margin-top:.7rem"><div class="mut" style="font-size:.74rem;margin-bottom:.2rem">📈 Equity curve — ROI kumulatif realized vs target ${d.target_pct}%</div>${roiChart(d.curve, d.target_pct)}</div>`;
    h+=`<div class="sub" style="margin-top:.6rem;background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:10px;padding:.55rem .8rem">
      🤖 <b>Strategi adaptif</b> (ROI Integral): ambang akurasi BELI = <b>${a.min_buy_accuracy}%</b> · target jual net <b>${a.take_profit_net_pct}%</b>
      ${a.roi_pct!=null?` · ROI basis <b>${a.roi_pct}%</b> (${esc(a.roi_basis||'integral')})`:''}
      ${(a.notes&&a.notes[0])?`<div class="mut" style="font-size:.72rem;margin-top:.25rem">${esc(a.notes[0])}</div>`:''}
      ${(a.notes||[]).map(n=>`<div class="mut" style="font-size:.74rem;margin-top:.2rem">• ${esc(n)}</div>`).join('')}</div>`;
    if(d.trades&&d.trades.length){
      h+=`<div style="margin-top:.6rem;font-size:.76rem"><span class="mut">Riwayat:</span> `+d.trades.slice(-6).reverse().map(t=>`<span class="badge ${t.win?'buy':'sell'}" title="${t.lots} lot @ ${fmt(t.avg_price)}→${fmt(t.exit_price)}">${t.ticker} ${t.roi_pct>=0?'+':''}${t.roi_pct}%</span>`).join(' ')+`</div>`;
    }
    $('#port-roi').innerHTML=h;
  }catch(e){ $('#port-roi').innerHTML='<p class="sub">Gagal memuat ROI.</p>'; }
}
function roiChart(curve, target){
  if(!curve||!curve.length) return '<div class="sub" style="font-size:.76rem">Belum ada transaksi tertutup — kurva muncul setelah Anda menutup posisi via tombol 💰 Jual.</div>';
  const W=600,H=170,pL=42,pR=14,pT=14,pB=22, n=curve.length;
  const ys=curve.map(p=>p.cum_roi_pct);
  const vmin=Math.min(0,target,...ys), vmax=Math.max(target,0.5,...ys), span=(vmax-vmin)||1;
  const X=i=> pL + (n<=1?0.5:i/(n-1))*(W-pL-pR);
  const Y=v=> pT + (1-(v-vmin)/span)*(H-pT-pB);
  const path='M'+curve.map((p,i)=>`${X(i).toFixed(1)},${Y(p.cum_roi_pct).toFixed(1)}`).join(' L');
  const last=ys[n-1], lineC=last>=target?'var(--buy)':last>=0?'var(--brand-2)':'var(--sell)';
  const y0=Y(0).toFixed(1), yT=Y(target).toFixed(1);
  const dots=curve.map((p,i)=>`<circle cx="${X(i).toFixed(1)}" cy="${Y(p.cum_roi_pct).toFixed(1)}" r="3" fill="${p.cum_roi_pct>=target?'var(--buy)':'var(--sell)'}"><title>#${p.n} ${esc(p.ticker)} ${p.date?'· '+esc(p.date):''} · kumulatif ${p.cum_roi_pct}%</title></circle>`).join('');
  return `<div style="overflow-x:auto"><svg viewBox="0 0 ${W} ${H}" style="width:100%;min-width:380px;height:auto">
    <line x1="${pL}" y1="${y0}" x2="${W-pR}" y2="${y0}" stroke="var(--line)"/>
    <line x1="${pL}" y1="${yT}" x2="${W-pR}" y2="${yT}" stroke="var(--buy)" stroke-dasharray="5 4" opacity=".75"/>
    <text x="${W-pR}" y="${(yT-4)}" fill="var(--buy)" font-size="10" text-anchor="end">target ${target}%</text>
    <text x="6" y="${(+y0+3)}" fill="var(--mute)" font-size="10">0%</text>
    <path d="${path}" fill="none" stroke="${lineC}" stroke-width="2"/>${dots}
    <text x="${pL}" y="${H-6}" fill="var(--mute)" font-size="9">#1</text>
    <text x="${W-pR}" y="${H-6}" fill="var(--mute)" font-size="9" text-anchor="end">#${n} (${last>=0?'+':''}${last}%)</text>
  </svg></div>`;
}
function openSell(id, tk, maxLots, price, feeSell){
  const f=`<section class="glass-panel" style="margin-bottom:1.4rem;border-left:4px solid var(--sell)">
    <div class="between"><h3 class="sec" style="margin:0">💰 Jual ${tk}</h3><button class="btn icon" onclick="$('#port-sell').innerHTML=''">✕</button></div>
    <p class="sub" style="margin:.2rem 0 .7rem">Jual sebagian/penuh. Sinkron: catat ROI → tambah cash RDN → kurangi posisi.</p>
    <div class="row">
      <label class="fld"><span class="l">Lot dijual (maks ${maxLots})</span><input id="sell-lots" type="number" value="${maxLots}" min="1" max="${maxLots}" oninput="sellPreview(${feeSell})"></label>
      <label class="fld"><span class="l">Harga jual (Rp)</span><input id="sell-price" type="number" value="${price}" oninput="sellPreview(${feeSell})"></label>
      <button class="btn ghost" onclick="$('#sell-lots').value=${Math.max(1,Math.ceil(maxLots/2))};sellPreview(${feeSell})" title="separuh">½</button>
      <button class="btn ghost" onclick="$('#sell-lots').value=${maxLots};sellPreview(${feeSell})" title="semua">Semua</button>
      <button class="btn primary" onclick="sellExec(${id},'${tk}')">✅ Konfirmasi Jual</button>
    </div>
    <div id="sell-preview" class="sub" style="margin-top:.6rem"></div></section>`;
  $('#port-sell').innerHTML=f; $('#port-sell').scrollIntoView({behavior:'smooth',block:'center'}); sellPreview(feeSell);
}
function sellPreview(feeSell){
  const lots=+$('#sell-lots').value||0, price=+$('#sell-price').value||0;
  const gross=lots*100*price, net=Math.round(gross*(1-(feeSell||0.25)/100));
  $('#sell-preview').innerHTML=`Nilai jual: <b>${lots} lot × ${fmt(price)}</b> = ${fmt(gross)} kotor → <b style="color:var(--buy)">${fmt(net)} bersih</b> (stlh fee ${feeSell||0.25}%) masuk cash RDN.`;
}
async function sellExec(id, tk){
  const lots=+$('#sell-lots').value, price=+$('#sell-price').value;
  if(!lots||lots<1||!price||price<=0){ toast('Isi lot & harga jual yang valid.'); return; }
  try{ const r=await (await fetch(`/api/portfolio/${id}/sell?exit_price=${price}&lots=${lots}`,{method:'POST'})).json();
    if(!r.ok){ toast(r.detail||'Gagal menjual.'); return; }
    const sisa = r.remaining_lots===0?'habis':r.remaining_lots+' lot tersisa';
    toast(`✓ ${tk} jual ${r.sold_lots} lot · ROI ${r.roi_pct>=0?'+':''}${r.roi_pct}% · +${fmt(r.proceeds)} ke cash · ${sisa}`);
    $('#port-sell').innerHTML=''; loadPortfolio();
  }catch(e){ toast('Gagal menjual.'); }
}
async function loadRDN(){
  try{ const b=await api('/api/portfolio/rdn'); const t=b.total;
    window._rdnBreakdown = b;
    let h=`<div class="grid g-3" style="margin-bottom:.9rem">
      ${miniStat('1. Portofolio Trading Harian', fmt(t.trading_value), `${t.trading_pct??'–'}% ekuitas · P/L: ${t.trading_pl >= 0 ? '+' : ''}${fmt(t.trading_pl)}`)}
      ${miniStat('2. Portofolio Investasi Saham', fmt(t.investasi_value), `${t.investasi_pct??'–'}% ekuitas · P/L: ${t.investasi_pl >= 0 ? '+' : ''}${fmt(t.investasi_pl)}`)}
      ${miniStat('3. Portofolio Investasi Emas', fmt(t.gold_value), `${t.gold_pct??'–'}% ekuitas · P/L: ${(b.rdn.find(r => r.broker === 'Tring Pegadaian')?.gold_pl || 0) >= 0 ? '+' : ''}${fmt(b.rdn.find(r => r.broker === 'Tring Pegadaian')?.gold_pl || 0)}`)}
    </div>`;
    h+=`<div class="grid g-1" style="margin-bottom:.9rem; background: var(--bg-card); padding: .75rem 1rem; border-radius: 10px; border: 1px solid var(--line);">
      <div class="between" style="font-weight: 700;">
        <span>💰 Total Ekuitas Gabungan (Net Worth)</span>
        <span style="font-size: 1.15rem; color: var(--buy);">${fmt(t.equity)}</span>
      </div>
      <div class="between mut" style="font-size: .76rem; margin-top: .25rem;">
        <span>Total Saldo Cash Standby: ${fmt(t.cash)} (${t.cash_pct??'–'}%)</span>
        <span>Aset Saham: ${fmt(t.asset_value)} (${t.asset_pct??'–'}%) · Aset Emas: ${fmt(t.gold_value)} (${t.gold_pct??'–'}%)</span>
      </div>
    </div>`;
    h+= b.rdn.length ? b.rdn.map(rdnCard).join('') : '<div class="empty">Belum ada RDN. Impor PDF atau isi cash manual.</div>';
    h+=`<p class="sub" style="margin-top:.6rem">${esc(b.catatan)}</p>`;
    $('#rdn-out').innerHTML=h;

    // Populate the Trading Plan broker list
    const planBrok = $('#plan-broker');
    if (planBrok && b.rdn.length) {
      const stockBrokers = b.rdn.filter(r => r.broker !== 'Tring Pegadaian');
      planBrok.innerHTML = stockBrokers.map(r => `<option value="${r.broker}">${r.broker} (Cash: ${fmt(r.cash)})</option>`).join('');
    }

    // Sinkronisasi ke tab Trading Plan
    if(t.equity > 0){
      $('#idle').value = t.equity;
    }
    if(t.target_emiten > 0){
      $('#nstk').value = t.target_emiten;
    }
    
    // Tampilkan pemberitahuan out-of-sync di Decision Center jika data berubah
    const verdictEl = $('#verdict');
    if (verdictEl && !verdictEl.innerHTML.includes('Portofolio diperbarui')) {
      if (verdictEl.querySelector('.mut') || verdictEl.innerHTML.includes('BELI')) {
        verdictEl.insertAdjacentHTML('afterbegin', `<div class="badge warning" style="display:block;margin-bottom:.5rem;text-align:center;font-weight:600">⚠️ Portofolio diperbarui. Jalankan Funnel kembali untuk menyelaraskan keputusan.</div>`);
      }
    }

    // Jalankan kalkulasi Money Management & Taichi otomatis
    mm().then(d => {
      if(d && d.bid_fund){
        $('#tmodal').value = d.bid_fund;
        taichi();
      }
    });

  }catch(e){ $('#rdn-out').innerHTML='<div class="empty">Gagal memuat RDN.</div>'; }
  loadDashMM(); loadDashROI();   // jaga Dashboard tetap sinkron dgn perubahan cash/posisi
}
function rdnCard(r){
  const a=r.advice||{}, full=r.emiten>=r.target_emiten;
  const trend = window._marketTrend || 'UPTREND';
  const isUp = trend === 'UPTREND';
  
  if (r.broker === 'Tring Pegadaian') {
    const goldPlUp = (r.gold_pl || 0) >= 0;
    return `<div class="glass-panel" style="margin-bottom:.7rem;padding:.9rem 1.1rem; border-left:4px solid var(--hold)">
      <div class="between" style="align-items:flex-start">
        <div class="flex" style="gap:.5rem;flex-wrap:wrap;align-items:center">
          <b style="font-size:1.02rem">🪙 ${esc(r.broker)}</b>
          <span class="badge na" style="font-size:.58rem">Emas Digital</span>
        </div>
        <div style="text-align:right">
          <div class="mut" style="font-size:.62rem">NILAI EMAS</div>
          <b style="font-size:1.05rem;color:var(--hold)">${fmt(r.gold_value)}</b>
        </div>
      </div>
      <div class="grid g-3" style="gap:.6rem;margin:.7rem 0 .55rem;font-size:.8rem">
        <div>⚖️ Saldo <b>${r.gold_balance_grams}g</b></div>
        <div>💰 Avg Buy <b>${fmt(r.gold_avg_price)}/g</b></div>
        <div>💰 Live Price <b>${fmt(r.gold_price_g)}/g</b></div>
      </div>
      <div class="grid g-3" style="gap:.6rem;margin:.55rem 0;font-size:.8rem;border-top:1px dashed var(--line);padding-top:.55rem">
        <div>💵 Total Modal <b>${fmt(r.gold_cost)}</b></div>
        <div>${goldPlUp?'📈':'📉'} P/L Emas <b class="${goldPlUp?'pl-up':'pl-down'}">${goldPlUp?'+':''}${fmt(r.gold_pl)}</b> <span class="mut">${r.gold_pl_pct??'–'}%</span></div>
        <div>📊 Porsi Portofolio <b>${r.gold_pct??'–'}%</b></div>
      </div>
    </div>`;
  }
  
  let integrationAdvice = '';
  if (r.broker === 'Profits Anywhere') {
    if (!isUp) {
      integrationAdvice = `<div style="margin-top:.45rem;padding:.5rem .6rem;border-radius:8px;background:rgba(234,179,8,.08);border:1px solid rgba(234,179,8,.2);font-size:.74rem;line-height:1.4">
        🟡 <b>Rekomendasi Taktis (IHSG Downtrend)</b>: Pasar saham sedang lesu. Disarankan mengamankan Dana Cadangan Anda sebesar <b>${fmt(a.reserve_fund)}</b> ke <b>Emas Digital (Tring Pegadaian)</b> agar kas berkembang likuid & aman dari penurunan.
      </div>`;
    } else {
      integrationAdvice = `<div style="margin-top:.45rem;padding:.5rem .6rem;border-radius:8px;background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.2);font-size:.74rem;line-height:1.4">
        🟢 <b>Rekomendasi Taktis (IHSG Uptrend)</b>: Pasar saham sedang bullish. Jika ada peluang BELI saham syariah yang valid, pertimbangkan mencairkan emas di <b>Tring Pegadaian</b> secara instan ke RDN untuk dieksekusi.
      </div>`;
    }
  }
  let goldHtml = '';
  if (r.gold_balance_grams) {
    const goldPlUp = (r.gold_pl || 0) >= 0;
    goldHtml = `<div class="grid g-3" style="gap:.6rem;margin:.55rem 0;font-size:.8rem;border-top:1px dashed var(--line);padding-top:.45rem">
      <div>🪙 Emas <b>${r.gold_balance_grams}g</b> <span class="mut">${r.gold_pct??'–'}%</span></div>
      <div>💰 Nilai Emas <b>${fmt(r.gold_value)}</b> <span class="mut">@${fmt(r.gold_price_g)}/g</span></div>
      <div>${goldPlUp?'📈':'📉'} P/L Emas <b class="${goldPlUp?'pl-up':'pl-down'}">${goldPlUp?'+':''}${fmt(r.gold_pl)}</b> <span class="mut">${r.gold_pl_pct??'–'}%</span></div>
    </div>`;
  }
  let detailHtml = '';
  if(r.cash_at_broker != null || r.cash_at_rdn != null) {
    const cb = r.cash_at_broker || 0;
    const crdn = r.cash_at_rdn || 0;
    const net_cash = cb + crdn;
    const sh_val = r.cost || 0;
    const eq = net_cash + sh_val;
    const cash_pct = eq ? ((net_cash / eq) * 100).toFixed(2) : '0.00';
    const asset_pct = eq ? ((sh_val / eq) * 100).toFixed(2) : '0.00';
    const cur_ratio = sh_val ? ((net_cash / sh_val) * 100).toFixed(2) : '0.00';

    detailHtml = `
    <div style="margin-top:.7rem;padding:.7rem;border-radius:10px;background:rgba(255,255,255,.02);border:1px solid var(--line);font-size:.76rem">
      <div style="font-weight:700;margin-bottom:.4rem;color:var(--brand-2)">📊 Detail Parameter Laporan PDF (Klik untuk Penjelasan)</div>
      <div class="between" style="padding:.2rem 0;cursor:pointer;border-bottom:1px dashed var(--line)" onclick="showExplain('cash_at_broker')">
        <span class="dim">A. Cash at Broker</span>
        <b class="${cb < 0 ? 'pl-down' : ''}">${cb < 0 ? '-' : ''}${fmt(Math.abs(cb))}</b>
      </div>
      <div class="between" style="padding:.2rem 0;cursor:pointer;border-bottom:1px dashed var(--line)" onclick="showExplain('cash_at_rdn')">
        <span class="dim">B. Cash at RDN</span>
        <b>${fmt(crdn)}</b>
      </div>
      <div class="between" style="padding:.2rem 0;cursor:pointer;border-bottom:1px dashed var(--line)" onclick="showExplain('shares_value')">
        <span class="dim">C. Shares Value (Cost)</span>
        <b>${fmt(sh_val)}</b>
      </div>
      <div class="between" style="padding:.2rem 0;cursor:pointer;border-bottom:1px dashed var(--line)" onclick="showExplain('equity')">
        <span class="dim">D. Equity (A+B+C)</span>
        <b style="color:var(--text)">${fmt(eq)}</b>
      </div>
      <div class="between" style="padding:.2rem 0;cursor:pointer;border-bottom:1px dashed var(--line)" onclick="showExplain('cash_equity_pct')">
        <span class="dim">1. Cash/Equity Ratio (A+B)/D</span>
        <b style="color:var(--brand-2)">${cash_pct}%</b>
      </div>
      <div class="between" style="padding:.2rem 0;cursor:pointer;border-bottom:1px dashed var(--line)" onclick="showExplain('shares_equity_pct')">
        <span class="dim">2. Shares Value/Equity C/D</span>
        <b style="color:var(--brand-2)">${asset_pct}%</b>
      </div>
      <div class="between" style="padding:.2rem 0;cursor:pointer" onclick="showExplain('current_ratio')">
        <span class="dim">3. Current Ratio (A+B)/C</span>
        <b style="color:var(--buy)">${cur_ratio}%</b>
      </div>
    </div>`;
  }

  const isUSD = r.currency === 'USD';
  const aSymbol = isUSD ? '$' : 'Rp ';
  const aFmt = val => {
    if (val === null || val === undefined || val === '') return '—';
    return isUSD ? Number(val).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}) : fmt(val);
  };

  return `<div class="glass-panel" style="margin-bottom:.7rem;padding:.9rem 1.1rem">
    <div class="between" style="align-items:flex-start">
      <div class="flex" style="gap:.5rem;flex-wrap:wrap;align-items:center">
        <b style="font-size:1.02rem">${esc(r.broker)}</b>
        ${r.rdn?`<span class="badge na" style="font-size:.58rem">${esc(r.rdn)}</span>`:''}
        ${r.bank?`<span class="mut" style="font-size:.7rem">${esc(r.bank)}</span>`:''}
        <span class="badge ${full?'buy':'warning'}">${r.emiten}/${r.target_emiten} emiten</span>
        ${isUSD ? `<span class="badge buy" style="font-size:.58rem">USD</span>` : ''}
      </div>
      <div style="text-align:right"><div class="mut" style="font-size:.62rem">EKUITAS (IDR)</div><b style="font-size:1.05rem">Rp ${fmt(r.equity)}</b></div>
    </div>
    <div class="grid g-3" style="gap:.6rem;margin:.55rem 0;font-size:.8rem">
      <div>💵 Cash <b>${isUSD ? '$' + Number(r.cash).toLocaleString('en-US', {minimumFractionDigits: 2}) : 'Rp ' + fmt(r.cash)}</b>${isUSD ? ` <span class="mut" style="font-size:.68rem">(Rp ${fmt(r.cash_idr)})</span>` : ''} <span class="mut">${r.cash_pct??'–'}%</span></div>
      <div>📦 Aset Saham <b>Rp ${fmt(r.asset_value)}</b> <span class="mut">${r.asset_pct??'–'}%</span></div>
      <div>${(r.pl||0)>=0?'📈':'📉'} P/L Saham <b class="${(r.pl||0)>=0?'pl-up':'pl-down'}">${(r.pl||0)>=0?'+':''}Rp ${fmt(Math.abs(r.pl))}</b> <span class="mut">${r.pl_pct??'–'}%</span></div>
    </div>
    ${goldHtml}
    <div class="mut" style="font-size:.7rem;margin:-.2rem 0 .4rem">💸 Biaya: beli ${r.fee_buy_pct}% · jual ${r.fee_sell_pct}% (pulang-pergi ${r.advice?.roundtrip_pct??'–'}%) — target jual ≥ +${r.advice?.net_profit_min_pct??'–'}% utk profit bersih</div>
    ${r.cash_pct!=null?`<div class="bar" style="height:7px"><i style="width:${(r.asset_pct||0)+(r.gold_pct||0)}%;background:var(--brand-2)"></i></div>
      <div class="mut" style="font-size:.66rem;margin:.2rem 0 .5rem">saham ${r.asset_pct??0}% · emas ${r.gold_pct??0}% · cash ${r.cash_pct??0}%</div>`:''}
    ${detailHtml}
    <div style="background:rgba(255,255,255,.04);border:1px solid var(--line);border-radius:10px;padding:.6rem .8rem;font-size:.78rem;margin-top:.6rem">
      <b>🧮 Saran Money Management (${r.currency})</b>
      <div style="margin-top:.3rem">Dana trading <b>${a.trading_fund_pct||50}%</b> = <b>${aSymbol}${aFmt(a.trading_fund)}</b> · cadangan ${aSymbol}${aFmt(a.reserve_fund)}</div>
      <div>Per emiten (÷${r.target_emiten}): <b>${aSymbol}${aFmt(a.per_emiten)}</b> · slot kosong <b>${a.open_slots??'–'}</b> · siap deploy <b style="color:var(--buy)">${aSymbol}${aFmt(a.deployable_now)}</b></div>
      ${a.risk_per_bid!=null?`<div class="mut">Per bid: risk ${a.risk_pct}% = ${aSymbol}${aFmt(a.risk_per_bid)} · target ${a.profit_pct}% = ${aSymbol}${aFmt(a.profit_per_bid)}</div>`:''}
      <div style="margin-top:.35rem">${esc(a.note||'')}</div>
      ${integrationAdvice}
      ${r.health?`<div class="mut" style="margin-top:.2rem">ℹ️ ${esc(r.health)}</div>`:''}
    </div>
  </div>`;
}
function showExplain(param){
  const explanations = {
    cash_at_broker: {
      title: "💵 Cash at Broker (Kas di Sekuritas / Broker)",
      html: `<p style="line-height:1.6"><b>Cash at Broker</b> menunjukkan saldo kas transaksi Anda di dalam akun sekuritas.</p>
             <p style="line-height:1.6;margin-top:.5rem">Di Profits Anywhere (Phintraco), nilai negatif (seperti <b>-Rp 2.413.114</b>) berarti ada transaksi pembelian saham yang baru Anda lakukan dan sedang menunggu hari penyelesaian (<i>settlement</i> T+2). Uang ini <b>bukan hutang bunga/riba</b>, melainkan kewajiban bayar yang akan ditarik otomatis dari kas RDN Anda oleh sistem broker pada hari penyelesaian transaksi kerja kedua setelah pembelian.</p>`
    },
    cash_at_rdn: {
      title: "🏦 Cash at RDN (Kas di Rekening Dana Nasabah)",
      html: `<p style="line-height:1.6"><b>Cash at RDN</b> adalah saldo uang tunai riil Anda yang berada di dalam Rekening Dana Nasabah (RDN) Bank penampung (dalam hal ini Bank BCA).</p>
             <p style="line-height:1.6;margin-top:.5rem">Uang ini adalah uang tunai murni (<i>cash</i>) milik Anda sendiri yang aman, likuid, siap digunakan kapan saja untuk membeli saham baru lewat aplikasi broker, atau ditarik kembali (<i>withdraw</i>) ke rekening bank pribadi Anda.</p>`
    },
    shares_value: {
      title: "📦 Shares Value (Nilai Aset Saham)",
      html: `<p style="line-height:1.6"><b>Shares Value</b> merupakan total nilai modal bersih yang sedang tertanam dalam bentuk investasi saham Anda saat ini (di dalam portofolio Anda terdapat ANTM, PTBA, dan KLBF).</p>
             <p style="line-height:1.6;margin-top:.5rem">Angka ini dihitung berdasarkan total lembar saham dikalikan harga beli rata-rata (<i>cost value</i>), mencerminkan berapa besar dana dingin Anda yang sedang bekerja di pasar saham.</p>`
    },
    equity: {
      title: "🛡️ Equity (Ekuitas / Total Kekayaan)",
      html: `<p style="line-height:1.6"><b>Equity</b> adalah total kekayaan bersih Anda di akun sekuritas ini.</p>
             <p style="line-height:1.6;margin-top:.5rem">Dihitung dengan menjumlahkan seluruh aset Anda:
             <br><b style="color:var(--brand-2)">Kas Broker + Kas RDN + Nilai Saham</b>.
             <br>Dalam hal ini: <i>-Rp 2.413.114 + Rp 5.000.000 + Rp 2.409.500 = Rp 4.996.386</i>. Angka ini mencerminkan modal riil sesungguhnya yang Anda miliki saat ini.</p>`
    },
    cash_equity_pct: {
      title: "📊 Cash / Equity Ratio (Persentase Uang Kas)",
      html: `<p style="line-height:1.6"><b>Cash / Equity Ratio</b> adalah persentase uang tunai bersih Anda dibandingkan dengan total kekayaan (Ekuitas) Anda.</p>
             <p style="line-height:1.6;margin-top:.5rem">Dengan rasio sebesar <b>51.78%</b>, artinya setengah dari total kekayaan Anda saat ini aman dalam bentuk uang tunai (likuid). Ini menunjukkan kondisi portofolio yang sangat aman dan memiliki amunisi cadangan yang melimpah untuk memborong saham potensial berikutnya.</p>`
    },
    shares_equity_pct: {
      title: "📈 Shares Value / Equity Ratio (Persentase Saham)",
      html: `<p style="line-height:1.6"><b>Shares Value / Equity Ratio</b> adalah persentase porsi modal yang telah Anda investasikan ke dalam bentuk saham dibandingkan total kekayaan Anda.</p>
             <p style="line-height:1.6;margin-top:.5rem">Di sini, porsinya adalah <b>48.22%</b>, menunjukkan alokasi aset yang sangat terkontrol dan seimbang, tidak melampaui batas batas aman (menghindari <i>over-allocation</i> di satu kelas aset).</p>`
    },
    current_ratio: {
      title: "🧮 Current Ratio (Rasio Likuiditas Kas ke Saham)",
      html: `<p style="line-height:1.6"><b>Current Ratio</b> adalah rasio perbandingan antara total uang tunai bersih Anda (Kas RDN + Kas Broker) dengan total nilai modal saham Anda.</p>
             <p style="line-height:1.6;margin-top:.5rem">Angka <b>107.36%</b> (di atas 100%) berarti uang tunai bersih Anda saat ini lebih besar daripada aset saham Anda. Kondisi ini mencerminkan taktik defensif yang sangat sehat, membuat Anda aman dari fluktuasi penurunan harga saham dan memiliki daya beli fleksibel.</p>`
    }
  };

  const item = explanations[param];
  if(!item) return;

  $('#modal').classList.add('open');
  const h3 = document.querySelector('#modal h3.sec');
  if(h3) h3.innerHTML = item.title;
  $('#modal-body').innerHTML = item.html;
  const footer = document.querySelector('#modal .modal > div:last-child');
  if(footer) footer.style.display = 'none';
}
async function saveRDN(){
  const broker=$('#rdn-broker').value, cash=+$('#rdn-cash').value||0, rdn=$('#rdn-no').value.trim()||null;
  const fb=$('#rdn-feeb').value, fs=$('#rdn-fees').value;
  const body={broker,cash,rdn, currency: /pluang/i.test(broker)?'USD':'IDR'};
  if(fb!=='') body.fee_buy_pct=+fb;
  if(fs!=='') body.fee_sell_pct=+fs;
  const d=await post('/api/accounts',body);
  if(d&&d.detail){ toast(d.detail); return; }
  toast(broker+' RDN disimpan'+(body.currency==='USD'?' (USD)':'')+'.'); $('#rdn-cash').value=0; $('#rdn-no').value=''; $('#rdn-feeb').value=''; $('#rdn-fees').value=''; loadRDN();
}
async function saveGold(){
  const grams = parseFloat($('#gold-grams').value) || 0;
  const avg = parseFloat($('#gold-avg').value) || 0;
  if (grams <= 0 || avg <= 0) { toast('Lengkapi saldo gram dan harga rata-rata.'); return; }
  
  try {
    const body = {
      broker: 'Tring Pegadaian',
      cash: 0,
      fee_buy_pct: 0,
      fee_sell_pct: 0,
      gold_balance_grams: grams,
      gold_avg_price: avg
    };
    const d = await post('/api/accounts', body);
    if(d && d.detail){ toast(d.detail); return; }
    toast('Saldo Emas Tring Pegadaian disimpan.');
    $('#gold-grams').value = '';
    $('#gold-avg').value = '';
    loadRDN();
  } catch(e) {
    toast('Gagal menyimpan emas: ' + e);
  }
}
function plStat(l,v,pct){ const up=(v||0)>=0; return `<div class="cardlet"><div class="lbl mut" style="font-size:.7rem;text-transform:uppercase">${l}</div>
  <div class="num ${up?'pl-up':'pl-down'}" style="font-size:1.3rem;font-weight:800;margin-top:.1rem">${up?'+':''}${fmt(v)}${pct?'%':''}</div></div>`; }
async function addPosition(){
  const ticker=$('#p-tk').value.trim().toUpperCase(), lots=+$('#p-lot').value, avg_price=+$('#p-avg').value, type=$('#p-type').value;
  if(!ticker||!lots||!avg_price){ toast('Lengkapi kode, lot, harga.'); return; }
  const d=await post('/api/portfolio',{ticker,lots,avg_price,type});
  if(d.detail){ toast(d.detail); return; } $('#p-tk').value=''; toast(ticker+' ditambahkan.'); loadPortfolio();
}
async function delPosition(id){ if(!confirm('Hapus posisi ini?'))return;
  await fetch('/api/portfolio/'+id,{method:'DELETE'}); toast('Posisi dihapus.'); loadPortfolio(); }

/* ---- impor portofolio dari gambar/PDF (vision) ---- */
async function uploadPortfolio(){
  const f=$('#port-file').files[0];
  if(!f){ toast('Pilih file gambar/PDF dulu.'); return; }
  const broker=$('#port-broker').value, engine=$('#port-engine').value||'ocr';
  const how=engine==='ocr'?'Membaca (OCR lokal)':'AI membaca';
  $('#port-up-out').innerHTML=`<div class="flex" style="margin-top:.6rem"><span class="spin"></span><span class="dim">${how} ${esc(f.name)}…</span></div>`;
  const fd=new FormData(); fd.append('file', f);
  const q=new URLSearchParams({engine}); if(broker)q.set('broker',broker);
  try{ const d=await (await fetch('/api/portfolio/import?'+q,{method:'POST',body:fd})).json();
    if(!d.ok){ $('#port-up-out').innerHTML=`<p class="dim" style="color:var(--sell);margin-top:.5rem">${esc(d.error||d.detail||'Gagal membaca')}</p>`; return; }
    window._extracted=d;
    if(d.doc_type==='history') renderHistory(d); else renderExtracted(d);
  }catch(e){ $('#port-up-out').innerHTML=`<p class="dim">Gagal: ${e}</p>`; }
}
function renderHistory(d){
  const R=d.realized||{}, cf=d.cash_flow||{};
  let h=`<div class="between" style="margin:.7rem 0 .4rem"><span class="badge brand">riwayat transaksi · ${esc(d.broker||'')}</span>
    <span class="dim">${d.n_transactions} transaksi · ${(d.closed_trades||[]).length} tertutup · ${(d.open_positions||[]).length} terbuka</span></div>`;
  h+=`<p class="sub" style="margin:0 0 .5rem">BUY↔JUAL dicocokkan (FIFO) → ROI nyata masuk jurnal & melatih strategi adaptif. Posisi terbuka & cash diperbarui.</p>`;
  // realized summary
  if(R.n){ const c=(R.roi_pct||0)>=0?'pl-up':'pl-down';
    h+=`<div class="grid g-3" style="gap:.6rem;margin-bottom:.6rem">
      ${miniStat('Transaksi tertutup',R.n,R.wins+' menang')}
      ${plStat('ROI realized',R.roi_pct,true)}
      ${miniStat('Saldo cash (hitung)',fmt(cf.computed_balance),'deposit '+fmt(cf.deposit)+' · jual '+fmt(cf.sell_net))}</div>`; }
  // closed trades table
  if((d.closed_trades||[]).length){
    h+=`<table><thead><tr><th>Kode</th><th>Lot</th><th style="text-align:right">Beli→Jual</th><th style="text-align:right">ROI</th><th class="mut">Tgl</th></tr></thead><tbody>`;
    d.closed_trades.forEach(c=>{ const up=(c.roi_idr||0)>=0;
      h+=`<tr><td><span class="tkr">${c.ticker}</span></td><td class="num">${c.lots}</td>
        <td style="text-align:right" class="num">${fmt(c.avg_price)}→${fmt(c.exit_price)}</td>
        <td style="text-align:right" class="num ${up?'pl-up':'pl-down'}"><b>${c.roi_pct>=0?'+':''}${c.roi_pct}%</b></td>
        <td class="mut" style="font-size:.72rem">${esc(c.closed||'')}</td></tr>`; });
    h+=`</tbody></table>`;
  }
  // open positions
  if((d.open_positions||[]).length){
    h+=`<div style="margin-top:.5rem;font-size:.8rem"><b>Posisi terbuka:</b> `+d.open_positions.map(o=>`<span class="badge na">${o.ticker} ${o.lots}lot @ ${fmt(o.avg_price)}</span>`).join(' ')+`</div>`;
  }
  h+=`<div style="margin-top:.8rem"><button class="btn primary" onclick="applyHistory()">✅ Terapkan (catat ROI + perbarui posisi & cash)</button>
    <span class="mut" style="font-size:.72rem;margin-left:.5rem">Mengganti posisi broker ini sesuai riwayat. Trade yang sudah tercatat tidak digandakan.</span></div>`;
  $('#port-up-out').innerHTML=h;
}
async function applyHistory(){
  const f=$('#port-file').files[0]; if(!f){ toast('File hilang — unggah ulang.'); return; }
  const broker=$('#port-broker').value, engine=$('#port-engine').value||'ocr';
  const fd=new FormData(); fd.append('file', f);
  const q=new URLSearchParams({engine, save:'true'}); if(broker)q.set('broker',broker);
  toast('Menerapkan riwayat…');
  try{ const d=await (await fetch('/api/portfolio/import?'+q,{method:'POST',body:fd})).json();
    if(!d.ok){ toast('Gagal: '+(d.error||'')); return; }
    const n=(d.recorded_trades||[]).length;
    toast(`✓ ${n} ROI dicatat · posisi & cash diperbarui${d.cash_set?'':' (cash tak diubah)'}`);
    if(d.cash_warning) $('#port-up-out').innerHTML=`<p class="sub" style="color:#eab308">⚠ ${esc(d.cash_warning)}</p>`+$('#port-up-out').innerHTML;
    $('#port-file').value=''; loadPortfolio();
  }catch(e){ toast('Gagal menerapkan.'); }
}
function renderExtracted(d){
  if(!d.positions||!d.positions.length){ $('#port-up-out').innerHTML='<p class="dim" style="margin-top:.5rem">Tidak terbaca posisi saham. Coba PDF e-statement, gambar lebih tajam/zoom, ganti engine, atau tambah baris manual.</p>'; return; }
  let r=`<div class="between" style="margin:.7rem 0 .3rem"><span class="badge brand">${esc(d.engine)}${d.broker?' · '+esc(d.broker):''}</span>
    <span class="dim">${d.positions.length} baris terbaca${d.total_value?' · total '+fmt(d.total_value):''}</span></div>
    <p class="sub" style="margin:0 0 .5rem">⚠️ Periksa & <b>koreksi langsung</b> bila ada salah baca, lalu impor. (Avg “≈” = dihitung dari Last & P/L)</p>
    <table><thead><tr><th>Kode</th><th>Lot</th><th>Avg</th><th class="mut">Last</th><th class="mut">P/L</th><th></th></tr></thead><tbody id="ext-rows">`;
  d.positions.forEach(p=>r+=extRow(p));
  r+=`</tbody></table><div style="margin-top:.7rem"><button class="btn ghost" onclick="addExtRow()">+ Baris</button>
    <button class="btn primary" style="margin-left:.5rem" onclick="importExtracted()">➕ Update Portofolio</button></div>`;
  $('#port-up-out').innerHTML=r;
}
function extRow(p){ p=p||{}; const up=(p.pl||0)>=0;
  return `<tr><td><input class="ext-tk" value="${esc(p.ticker||'')}" style="width:78px;text-transform:uppercase"></td>
    <td><input class="ext-lot" type="number" value="${p.lots??''}" style="width:64px"></td>
    <td><input class="ext-avg" type="number" value="${p.avg_price??''}" style="width:88px" ${p.avg_derived?'title="dihitung dari Last & P/L"':''}></td>
    <td class="num mut" style="font-size:.8rem">${fmt(p.last_price)}</td>
    <td class="num ${up?'pl-up':'pl-down'}" style="font-size:.8rem">${p.pl!=null?((up?'+':'')+fmt(p.pl)):'-'}</td>
    <td><button class="del-btn" onclick="this.closest('tr').remove()">🗑</button></td></tr>`; }
function addExtRow(){ $('#ext-rows').insertAdjacentHTML('beforeend', extRow({})); }
async function importExtracted(){
  const broker=(window._extracted&&window._extracted.broker)||$('#port-broker').value||null;
  const imp=[];
  document.querySelectorAll('#ext-rows tr').forEach(tr=>{
    const tk=tr.querySelector('.ext-tk').value.trim().toUpperCase();
    const lot=parseInt(tr.querySelector('.ext-lot').value), avg=parseFloat(tr.querySelector('.ext-avg').value);
    if(tk && lot>0 && avg>0) imp.push({ticker:tk,lots:lot,avg_price:avg,broker});
  });
  if(!imp.length){ toast('Lengkapi kode, lot, dan avg minimal 1 baris.'); return; }
  toast(`Mengimpor & menyinkronkan posisi…`);
  try {
    const q=new URLSearchParams(); if(broker)q.set('broker',broker);
    const r=await post('/api/portfolio/sync?'+q, imp);
    if(r && !r.detail && r.ok) {
      toast(`✓ Portofolio ${broker || 'Profits Anywhere'} disinkronkan (${r.imported.length} saham).`);
      $('#port-up-out').innerHTML=''; $('#port-file').value=''; loadPortfolio();
    } else {
      toast('Gagal menyinkronkan: ' + (r.detail || r.error || 'Terjadi kesalahan'));
    }
  } catch(e) {
    toast('Gagal menyinkronkan: ' + e);
  }
}

/* ===================== SIMULASI EKSEKUSI HARIAN ===================== */
async function loadSimulation(){
  $('#sim-open').innerHTML='<div class="empty"><span class="spin"></span> Memuat simulasi…</div>';
  try{
    const d=await api('/api/simulation');
    const s=d.summary, L=d.learning||{};
    // --- kartu ringkasan ---
    const cum=s.cum_roi_pct, avg=s.avg_roi;
    $('#sim-summary').innerHTML=
      miniStat('Akurasi (win-rate)', s.win_rate==null?'—':s.win_rate+'%', s.n_closed+' simulasi tertutup')+
      plStat('ROI rata-rata / sinyal', avg==null?0:avg, true)+
      plStat('ROI akumulasi', cum==null?0:cum, true)+
      miniStat('Posisi terbuka', s.n_open, 'target '+(d.target_pct||6)+'% bersih · horizon 20 hari bursa');
    // --- equity curve (reuse roiChart: pakai cum_roi_pct rata-rata kumulatif) ---
    $('#sim-chart').innerHTML=roiChart(d.curve, d.target_pct||6);
    // --- learning ---
    let lh='';
    (L.notes||[]).forEach(n=>lh+=`<div class="alert-row"><span class="ic">🎓</span><span>${esc(n)}</span></div>`);
    const bands=Object.entries(d.by_conviction||{});
    if(bands.length){
      lh+=`<table style="margin-top:.6rem"><thead><tr><th>Band keyakinan saat sinyal</th><th class="num">n</th><th style="text-align:right">Win-rate</th><th style="text-align:right">Avg ROI</th></tr></thead><tbody>`;
      bands.forEach(([b,g])=>{ const up=(g.avg_roi||0)>=0;
        lh+=`<tr><td>${esc(b)}</td><td class="num">${g.n}</td>
          <td style="text-align:right" class="num">${g.win_rate}%</td>
          <td style="text-align:right" class="num ${up?'pl-up':'pl-down'}"><b>${g.avg_roi>=0?'+':''}${g.avg_roi}%</b></td></tr>`; });
      lh+=`</tbody></table>`;
    }
    lh+=`<p class="sub" style="margin-top:.6rem">Umpan balik otomatis: win-rate &amp; ROI simulasi dipakai <b>strategi adaptif</b> (ambang akurasi BELI di Pusat Keputusan) dan disisipkan sebagai <b>track-record ke prompt Claude</b> (Advisor) — algoritma makin selektif seiring data bertambah.</p>`;
    $('#sim-learning').innerHTML=lh;
    // --- posisi terbuka ---
    if(!d.open.length){ $('#sim-open').innerHTML='<div class="empty">Tidak ada posisi simulasi terbuka. Klik “📝 Rekam Rekomendasi Hari Ini”.</div>'; }
    else{
      let r='<table><thead><tr><th>Kode</th><th class="mut">Dibuka</th><th style="text-align:right">Entry</th><th style="text-align:right">Harga</th><th style="text-align:right">Target</th><th style="text-align:right">Stop</th><th style="text-align:right" title="ROI berjalan bersih (incl. fee)">P/L Jalan</th><th style="text-align:right" title="sisa hari bursa sebelum ditutup paksa">Sisa</th><th title="keyakinan gabungan saat sinyal">Conv.</th><th></th></tr></thead><tbody>';
      d.open.forEach(t=>{ const up=(t.running_roi_pct||0)>=0;
        r+=`<tr><td><span class="tkr">${t.ticker}</span></td>
          <td class="mut" style="font-size:.72rem">${esc(t.opened)}</td>
          <td style="text-align:right" class="num">${fmt(t.entry)}</td>
          <td style="text-align:right" class="num">${t.current_price==null?'—':fmt(t.current_price)}</td>
          <td style="text-align:right;color:var(--buy)" class="num">${fmt(t.target)}</td>
          <td style="text-align:right;color:var(--sell)" class="num">${fmt(t.stop_loss)}</td>
          <td style="text-align:right" class="num ${up?'pl-up':'pl-down'}"><b>${t.running_roi_pct==null?'—':(t.running_roi_pct>=0?'+':'')+t.running_roi_pct+'%'}</b></td>
          <td style="text-align:right" class="num">${t.days_left}h</td>
          <td>${t.conviction!=null?`<span class="badge ${t.conviction>=55?'buy':t.conviction>=45?'warning':'sell'}" title="${esc((t.reason||''))}">${t.conviction}</span>`:'—'}</td>
          <td style="text-align:right"><button class="del-btn" onclick="simDelete(${t.id})" title="Hapus simulasi">🗑</button></td></tr>`; });
      $('#sim-open').innerHTML=r+'</tbody></table>';
    }
    // --- riwayat tertutup ---
    if(!d.closed.length){ $('#sim-closed').innerHTML='<div class="empty">Belum ada simulasi tertutup — hasil muncul setelah harga menyentuh Target/Stop atau lewat horizon.</div>'; }
    else{
      const reasonBadge=x=> x==='TARGET'?'<span class="badge buy">🎯 Target</span>':x==='STOP_LOSS'?'<span class="badge sell">🛑 Stop</span>':'<span class="badge warning">⏱ Horizon</span>';
      let r='<table><thead><tr><th>Kode</th><th class="mut">Dibuka→Ditutup</th><th style="text-align:right">Entry→Exit</th><th>Alasan</th><th style="text-align:right" title="ROI bersih (incl. fee beli+jual)">ROI</th><th class="num" title="hari bursa posisi terbuka">Hari</th><th title="keyakinan gabungan saat sinyal">Conv.</th><th></th></tr></thead><tbody>';
      d.closed.slice().reverse().forEach(t=>{ const up=(t.roi_pct||0)>=0;
        r+=`<tr><td><span class="tkr">${t.ticker}</span></td>
          <td class="mut" style="font-size:.72rem">${esc(t.opened)} → ${esc(t.closed)}</td>
          <td style="text-align:right" class="num">${fmt(t.entry)}→${fmt(t.exit_price)}</td>
          <td>${reasonBadge(t.exit_reason)}</td>
          <td style="text-align:right" class="num ${up?'pl-up':'pl-down'}"><b>${t.roi_pct>=0?'+':''}${t.roi_pct}%</b></td>
          <td class="num">${t.days_held??'—'}</td>
          <td>${t.conviction!=null?`<span class="badge ${t.conviction>=55?'buy':t.conviction>=45?'warning':'sell'}" title="${esc((t.reason||''))}">${t.conviction}</span>`:'—'}</td>
          <td style="text-align:right"><button class="del-btn" onclick="simDelete(${t.id})" title="Hapus dari riwayat">🗑</button></td></tr>`; });
      $('#sim-closed').innerHTML=r+'</tbody></table>';
    }
  }catch(e){ $('#sim-open').innerHTML='<div class="empty">Gagal memuat simulasi.</div>'; $('#sim-closed').innerHTML=''; }
}
async function simCapture(){
  toast('🧪 Menjalankan funnel & merekam rekomendasi BUY… bisa ~1 menit (75 saham)');
  try{
    const d=await (await fetch('/api/simulation/run?force=true',{method:'POST'})).json();
    if(!d.ok){ toast('Tidak direkam: '+(d.skipped||'')); return; }
    toast(`✓ ${d.added} simulasi baru direkam (dari ${d.buy_signals} sinyal BUY).`);
    loadSimulation();
  }catch(e){ toast('Gagal merekam simulasi.'); }
}
async function simEvaluate(){
  toast('⚖️ Mengevaluasi posisi simulasi (Target/Stop/horizon)…');
  try{
    const d=await (await fetch('/api/simulation/evaluate',{method:'POST'})).json();
    toast(d.closed?`✓ ${d.closed} simulasi ditutup — lihat riwayat & ROI.`:'✓ Evaluasi selesai — belum ada yang menyentuh Target/Stop/horizon.');
    loadSimulation();
  }catch(e){ toast('Gagal evaluasi.'); }
}
async function simDelete(id){ if(!confirm('Hapus simulasi ini?'))return;
  await fetch('/api/simulation/'+id,{method:'DELETE'}); toast('Simulasi dihapus.'); loadSimulation(); }

/* ===================== KOMODITAS ===================== */
async function loadCommodities(){
  _loaded.cmd=true;
  try{ const d=await api('/api/commodities');
    $('#emas-grid').innerHTML=d.emas_komoditas.map(cmd).join('');
    $('#perak-grid').innerHTML=d.perak_dinar.map(cmd).join('');
    $('#komo-note').textContent=d.catatan;
  }catch(e){ $('#emas-grid').innerHTML='<div class="empty">Gagal memuat.</div>'; }
}
function cmd(it){ const c=it.change_pct>=0?'var(--buy)':'var(--sell)';
  return `<div class="cmd"><div class="nm">${esc(it.nama)}</div>
    <div class="px num">${it.harga==null?'—':fmt(it.harga)}</div><div class="un">${esc(it.unit)}</div>
    <div class="chg" style="color:${c}">${it.change_pct==null?'':((it.change_pct>=0?'▲ +':'▼ ')+it.change_pct+'%')}</div>
    ${it.syariah?`<div class="sy">☪ ${esc(it.syariah)}</div>`:''}</div>`; }

/* ===================== ALERT & TELEGRAM ===================== */
function closeModal(){ $('#modal').classList.remove('open'); }
async function explainMetric(ticker, metric, status, value) {
  $('#modal').classList.add('open');
  const h3 = document.querySelector('#modal h3.sec') || document.querySelector('#modal-title');
  if(h3) h3.innerHTML = `🤖 Analisa Claude — ${metric}`;
  const footer = document.querySelector('#modal .modal > div:last-child');
  if(footer) footer.style.display = 'none';
  
  $('#modal-body').innerHTML = `
    <div class="flex" style="flex-direction:column;gap:.6rem;padding:.4rem 0">
      <div style="font-size:.85rem;background:rgba(255,255,255,.03);padding:.5rem;border-radius:6px;border:1px solid var(--line)">
        <div>Saham: <b>${ticker}</b></div>
        <div>Kriteria: <b>${metric}</b></div>
        <div>Nilai Aktual: <b style="color:var(--buy)">${value || '—'}</b> · Status: <span class="badge ${status === 'Lolos' || status.includes('HALAL') || status === 'PASS' ? 'buy' : 'sell'}">${status}</span></div>
      </div>
      <div id="metric-explanation-content">
        <div class="flex"><span class="spin"></span> <span class="dim">Meminta penjelasan Claude…</span></div>
      </div>
    </div>
  `;

  try {
    const eng = $('#adv-engine')?.value || 'auto';
    const r = await api(`/api/advisor/explain/${ticker}/${encodeURIComponent(metric)}?status=${encodeURIComponent(status)}&value=${encodeURIComponent(value)}&engine=${eng}`);
    if (r && r.detail === "Not Found") {
      document.getElementById('metric-explanation-content').innerHTML = `
        <p class="sub" style="color:var(--sell)"><b>Rute baru tidak ditemukan (Error 404).</b><br>Harap <b>jalankan ulang (restart) server backend FastAPI</b> Anda agar kode Python baru termuat.</p>
      `;
      return;
    }
    const explanationHtml = mdb(r.explanation || 'Tidak ada penjelasan.');
    document.getElementById('metric-explanation-content').innerHTML = `
      <div class="ai-text" style="font-size:.9rem;line-height:1.6;margin-top:.4rem">${explanationHtml}</div>
      <div class="mut" style="font-size:.65rem;margin-top:.8rem;border-top:1px solid var(--line);padding-top:.4rem">Dianalisa oleh: ${esc(r.model)}</div>
    `;
  } catch(e) {
    document.getElementById('metric-explanation-content').innerHTML = `<p class="sub" style="color:var(--sell)">Gagal memuat penjelasan dari AI Advisor.</p>`;
  }
}
async function checkAlerts(){
  $('#modal').classList.add('open');
  const h3 = document.querySelector('#modal h3.sec');
  if(h3) h3.innerHTML = '🔔 Alert';
  const footer = document.querySelector('#modal .modal > div:last-child');
  if(footer) footer.style.display = 'block';
  $('#modal-body').innerHTML='<div class="flex"><span class="spin"></span><span class="dim">Memindai peluang & portofolio…</span></div>';
  try{ const d=await api('/api/alerts'); const ic={market:'📊',entry:'🟢',profit:'💰',loss:'🔴',info:'ℹ️'};
    $('#modal-body').innerHTML = `<p class="sub" style="margin:0 0 .6rem">${d.jumlah} alert ditemukan.</p>` +
      d.alerts.map(a=>`<div class="alert-row"><span class="ic">${ic[a.tipe]||'•'}</span><span>${esc(a.teks)}</span></div>`).join('');
  }catch(e){ $('#modal-body').innerHTML='<p class="dim">Gagal memuat alert.</p>'; }
}
async function sendTelegram(){
  const st=await api('/api/telegram/status');
  if(!st.configured){ toast('Telegram belum dikonfigurasi (.env).'); return; }
  if(!confirm('Kirim ringkasan alert ke Telegram Anda sekarang?')) return;
  toast('Mengirim ke Telegram…');
  const d=await post('/api/telegram/send',{});
  toast(d.ok?'✓ Terkirim ke Telegram.':('Gagal: '+(d.error||'')));
}

/* ===================== MASTER DATA (rebuild) ===================== */
async function masterRebuild(){
  let st={}; try{ st=await api('/api/master/status'); }catch(e){}
  if(!confirm(`Perbarui master data fundamental dari yfinance?\nTerakhir build: ${st.last_build_iso||'-'} (${st.total??'?'} saham).\nProses bisa ~1–2 menit (75 saham).`)) return;
  toast('⚙️ Membangun ulang master data… tunggu ~1–2 menit');
  try{ const r=await post('/api/master/rebuild',{});
    toast(`✓ Master data diperbarui: ${r.ok}/${r.total} OK (gagal ${r.fail}).`); loadUniverse();
  }catch(e){ toast('Gagal rebuild: '+e); }
}

// Function to generate Profits Anywhere (Phintraco) style form mockup
function makePhintracoMockup(type, title, bgColor, fields, cleanTicker) {
  const fieldRows = fields.map(f => {
    if (f.underline) {
      return `
        <div style="display:flex; justify-content:space-between; align-items:flex-end; border-bottom:1px solid #cbd5e0; padding:0.35rem 0 0.1rem 0">
          <span style="color:#4a5568; font-size:0.76rem">${f.label}</span>
          <span style="font-weight:700; font-size:0.86rem; color:#2d3748">${f.value}</span>
        </div>
      `;
    } else {
      return `
        <div style="display:flex; justify-content:space-between; align-items:center; padding:0.25rem 0; color:#4a5568">
          <span style="font-size:0.76rem">${f.label}</span>
          <span style="font-weight:700; color:#2d3748; font-size:0.82rem">${f.value}</span>
        </div>
      `;
    }
  }).join('');

  return `
    <div style="background:#ffffff; border:2px solid ${bgColor}; border-radius:12px; box-shadow:0 8px 20px rgba(0,0,0,0.12); width:100%; max-width:300px; margin:0 auto; overflow:hidden; font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif">
      <!-- App Header -->
      <div style="background:${bgColor}; color:#ffffff; padding:0.55rem; text-align:center; font-weight:700; font-size:0.86rem; letter-spacing:0.5px">
        ${title}
      </div>
      
      <div style="background:#f4faf6; padding:0.8rem; display:flex; flex-direction:column; gap:0.4rem">
        <!-- Shares Code Field -->
        <div style="margin-bottom:0.15rem">
          <div style="color:#718096; font-size:0.7rem; margin-bottom:0.05rem">Shares Code</div>
          <div style="border-bottom:1px solid #4a5568; padding:0.05rem 0; font-size:0.9rem; font-weight:700; color:#1a202c">
            ${cleanTicker}
          </div>
        </div>
        
        <!-- Other fields -->
        ${fieldRows}
        
        <!-- Bid Offer table -->
        <div style="display:grid; grid-template-columns: repeat(4, 1fr); text-align:center; margin-top:0.35rem; border-top:1px dashed #cbd5e0; padding-top:0.35rem; font-size:0.72rem">
          <div style="font-weight:700; color:#4a5568">B.Lot</div>
          <div style="font-weight:700; color:#4a5568">Bid</div>
          <div style="font-weight:700; color:#4a5568">Offer</div>
          <div style="font-weight:700; color:#4a5568">O.Lot</div>
          <div style="color:#718096; margin-top:0.1rem">-</div>
          <div style="color:#718096; margin-top:0.1rem">-</div>
          <div style="color:#718096; margin-top:0.1rem">-</div>
          <div style="color:#718096; margin-top:0.1rem">-</div>
        </div>
        
        <!-- Session info -->
        <div style="display:flex; justify-content:center; gap:0.7rem; margin-top:0.35rem; font-size:0.7rem; color:#4a5568">
          <span style="display:flex; align-items:center; gap:3px">🔵 <span style="font-size:0.68rem">Order Session Day</span></span>
          <span style="display:flex; align-items:center; gap:3px">⚪ <span style="font-size:0.68rem">Good Till Cancel</span></span>
        </div>
        
        <!-- PIN -->
        <div style="display:flex; justify-content:space-between; align-items:flex-end; border-bottom:1px solid #cbd5e0; padding:0.35rem 0 0.1rem 0; margin-bottom:0.25rem">
          <span style="color:#4a5568; font-size:0.76rem">PIN</span>
          <span style="color:#718096; font-size:0.8rem">••••</span>
        </div>
        
        <!-- Bottom Button -->
        <div style="background:${bgColor}; color:#ffffff; padding:0.5rem; text-align:center; font-weight:700; border-radius:6px; font-size:0.8rem; margin-top:0.25rem; opacity:0.95; text-transform:uppercase">
          ${type}
        </div>
      </div>
    </div>
  `;
}

/* ===================== ACTIVE PLANNER INTEGRATION ===================== */
async function loadPlanTicker() {
  const ticker = $('#plan-ticker').value;
  if (!ticker) return;
  $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3"><span class="spin"></span> Memuat analisis teknikal…</div>';
  try {
    const d = await api('/api/analyze/' + ticker);
    if (d && d.technical) {
      window._planTechData = d.technical;
      $('#plan-price').value = d.technical.price || 0;
      calculateActivePlan();
    } else {
      $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3; color:var(--sell)">Gagal memuat analisis emiten.</div>';
    }
  } catch (e) {
    $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3; color:var(--sell)">Gagal memuat analisis emiten.</div>';
  }
}

function loadPlanBroker() {
  calculateActivePlan();
}

function togglePlanRiskType() {
  calculateActivePlan();
}

async function calculateActivePlan() {
  const ticker = $('#plan-ticker').value;
  const broker = $('#plan-broker').value;
  const buyPrice = +$('#plan-price').value;
  const mode = $('#plan-mode').value;
  const riskType = $('#plan-risk-type').value;

  if (!ticker) {
    $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3">Pilih saham syariah terlebih dahulu.</div>';
    $('#phintraco-guide-container').style.display = 'none';
    return;
  }
  if (!broker) {
    $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3">Belum ada akun broker/RDN aktif yang dipilih.</div>';
    $('#phintraco-guide-container').style.display = 'none';
    return;
  }
  if (!buyPrice || buyPrice <= 0) {
    $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3">Masukkan harga beli OB1 yang valid.</div>';
    $('#phintraco-guide-container').style.display = 'none';
    return;
  }

  // Lindungi terhadap race condition loading data portofolio & RDN
  if (!window._rdnBreakdown || !window._portfolioData) {
    $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3"><span class="spin"></span> Menghubungkan dengan RDN &amp; Portofolio…</div>';
    setTimeout(calculateActivePlan, 500);
    return;
  }

  // 1. Ambil data broker & cash
  const selectedRdn = (window._rdnBreakdown && window._rdnBreakdown.rdn || []).find(r => r.broker === broker);
  if (!selectedRdn) {
    $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3; color:var(--sell)">Data RDN broker tidak ditemukan.</div>';
    $('#phintraco-guide-container').style.display = 'none';
    return;
  }
  
  const rdnCash = selectedRdn.cash || 0;
  const bidFund = (selectedRdn.advice) ? selectedRdn.advice.per_emiten : 0;
  
  // 2. Ambil data portfolio posisi saat ini
  const pos = (window._portfolioData && window._portfolioData.positions || []).find(p => p.ticker === ticker && p.broker === broker);
  const currentLots = pos ? pos.lots : 0;
  const currentVal = pos ? pos.value : 0;

  // 3. Tentukan sisa alokasi emiten (diversifikasi)
  const maxBuyingCapacity = Math.max(0, bidFund - currentVal);
  // Alokasi yang diizinkan (dibatasi cash RDN)
  const maxAllowedBuyRp = Math.min(maxBuyingCapacity, rdnCash);

  // 4. Hitung lot & Rp rekomendasi beli
  const recommendedLots = Math.floor(maxAllowedBuyRp / (buyPrice * 100));
  const recommendedVal = recommendedLots * 100 * buyPrice;

  // 5. Tentukan parameter Cut Loss berdasarkan risk type (default / atr)
  let clPrice = null;
  let riskPct = 3.0; // default
  let atrMsg = '';
  
  const mmRiskPct = +$('#risk').value || 3.0;
  const mmProfitPct = +$('#profit').value || 6.0;
  riskPct = mmRiskPct;

  if (riskType === 'atr') {
    if (window._planTechData && window._planTechData.atr && window._planTechData.atr.value) {
      const atrVal = window._planTechData.atr.value;
      const rawCl = buyPrice - 2 * atrVal;
      const rawRiskPct = ((buyPrice - rawCl) / buyPrice) * 100;
      if (rawRiskPct > 5.0) {
        clPrice = Math.round(buyPrice * 0.95);
        riskPct = 5.0;
        atrMsg = `ATR: ${fmt(atrVal)} (SL 2×ATR melebihi batas 5%, dipotong ke 5%)`;
      } else {
        clPrice = Math.round(rawCl);
        riskPct = Math.round(rawRiskPct * 10) / 10;
        atrMsg = `ATR: ${fmt(atrVal)} (SL di 2×ATR = ${fmt(clPrice)}, setara risk ${riskPct}%)`;
      }
    } else {
      atrMsg = 'ATR tidak ditemukan, menggunakan default risk %';
    }
  }

  const scale = mmProfitPct / mmRiskPct;
  const targetProfitPct = Math.max(riskPct * 2, riskPct * scale);

  $('#active-plan-out').innerHTML = '<div class="empty" style="grid-column:span 3"><span class="spin"></span> Menghitung rencana trading…</div>';

  try {
    // 6. Request backend APIs
    const [taichiRes, rrrRes] = await Promise.all([
      post('/api/plan/taichi', {
        modal: maxAllowedBuyRp > 0 ? maxAllowedBuyRp : bidFund,
        market_price: buyPrice,
        mode: mode,
        cl_price: clPrice,
        risk_pct: riskPct
      }),
      post('/api/plan/rrr', {
        buy: buyPrice,
        cut_loss: clPrice,
        take_profit: null,
        risk_pct: riskPct,
        profit_pct: targetProfitPct,
        target_reward_mult: 2
      })
    ]);

    if (taichiRes.error || rrrRes.error) {
      const errMsg = taichiRes.error || rrrRes.error;
      $('#active-plan-out').innerHTML = `<div class="empty" style="grid-column:span 3; color:var(--sell)">Gagal menyusun rencana: ${esc(errMsg)}</div>`;
      $('#phintraco-guide-container').style.display = 'none';
      return;
    }

    // 7. Render 3 Kolom
    // --- KOLOM 1: MONEY MANAGEMENT & ALOKASI PORTFOLIO ---
    let col1WarningHtml = '';
    if (currentLots > 0) {
      col1WarningHtml += `<div class="badge hold" style="display:block;margin-bottom:.5rem">⚠️ Sudah memiliki posisi ${currentLots} lot (${fmt(currentVal)}) di broker ini.</div>`;
    }
    if (maxBuyingCapacity <= 0) {
      col1WarningHtml += `<div class="badge warning" style="display:block;margin-bottom:.5rem">❌ Nilai posisi saat ini sudah memenuhi/melebihi limit Bid Fund per emiten (${fmt(bidFund)}).</div>`;
    } else if (rdnCash < maxBuyingCapacity) {
      col1WarningHtml += `<div class="badge hold" style="display:block;margin-bottom:.5rem">⚠️ Saldo cash RDN (${fmt(rdnCash)}) lebih kecil dari sisa limit alokasi emiten (${fmt(maxBuyingCapacity)}).</div>`;
    }
    if (recommendedLots === 0 && maxAllowedBuyRp > 0) {
      col1WarningHtml += `<div class="badge warning" style="display:block;margin-bottom:.5rem">⚠️ Dana alokasi tersisa (${fmt(maxAllowedBuyRp)}) tidak cukup untuk membeli minimal 1 lot.</div>`;
    }

    let col1Html = `
      <section class="glass-panel" style="margin:0">
        <h3 class="sec">⚖️ Alokasi &amp; Batas Trading</h3>
        ${col1WarningHtml}
        
        <div class="grid g-2" style="gap:.5rem; margin-bottom:.8rem">
          ${miniStat('Cash RDN', fmt(rdnCash), broker)}
          ${miniStat('Limit Bid Fund', fmt(bidFund), 'Per Emiten')}
        </div>
        
        <div class="crow"><div class="nm">Holding Saat Ini</div><div class="tg">${currentLots} lot</div><b class="num">${fmt(currentVal)}</b></div>
        <div class="crow"><div class="nm">Sisa Limit Alokasi</div><div class="tg">Bid Fund - Holding</div><b class="num">${fmt(maxBuyingCapacity)}</b></div>
        <div class="crow" style="border-top:1px solid var(--line); padding-top:.5rem">
          <div class="nm" style="font-weight:700">Rekomendasi Beli Maks</div>
          <div class="tg">Sesuai MM &amp; Cash</div>
          <b class="num pl-up" style="font-size:1.1rem">${fmt(recommendedVal)}</b>
        </div>
        <div class="crow"><div class="nm">Besaran Trading</div><div class="tg">OB1 @ ${fmt(buyPrice)}</div><b class="num pl-up" style="font-size:1.1rem">${recommendedLots} Lot</b></div>
        
        <p class="sub" style="margin-top:.6rem">Dibatasi secara ketat oleh RDN cash dan diversifikasi Bid Fund untuk melindungi portofolio dari over-allocation.</p>
      </section>
    `;

    // --- KOLOM 2: TAICHI ENTRY PLAN ---
    let taichiWarningHtml = '';
    if (maxAllowedBuyRp <= 0) {
      taichiWarningHtml = `<div class="badge sell" style="display:block;margin-bottom:.5rem">⚠️ Alokasi 0 lot. Simulasi Taichi di bawah ini menggunakan limit default per emiten (${fmt(bidFund)}).</div>`;
    }
    
    let taichiTableRows = '';
    taichiRes.open_buy.forEach(o => {
      taichiTableRows += `
        <tr>
          <td><b>${o.titik}</b></td>
          <td style="text-align:right" class="num">${fmt(o.harga)}</td>
          <td style="text-align:right" class="num">${o.lot}</td>
          <td style="text-align:right" class="num">${fmt(o.nilai)}</td>
        </tr>
      `;
    });

    let col2Html = `
      <section class="glass-panel" style="margin:0">
        <h3 class="sec">☯️ Rencana Entry Taichi</h3>
        ${taichiWarningHtml}
        <div class="between" style="margin-bottom:.5rem">
          <span class="badge brand">${taichiRes.mode} · risk ${taichiRes.risk_pct}%</span>
          <span class="dim">Total ${taichiRes.total_lot} lot · avg <b class="num" style="color:var(--text)">${fmt(taichiRes.average_jika_full)}</b></span>
        </div>
        <table>
          <thead>
            <tr>
              <th>Titik</th>
              <th style="text-align:right">Harga</th>
              <th style="text-align:right">Lot</th>
              <th style="text-align:right">Nilai</th>
            </tr>
          </thead>
          <tbody>
            ${taichiTableRows}
          </tbody>
        </table>
        <div class="crow" style="margin-top:.6rem"><div class="nm">Area Gagal Plan (CL)</div><div class="tg">3 tick di bawah OB3</div><b class="num pl-down">${fmt(taichiRes.cash_cl_area)}</b></div>
        <p class="sub">${esc(taichiRes.catatan)}</p>
      </section>
    `;

    // --- KOLOM 3: RISK-REWARD RATIO & TARGET ---
    let ruleWarnings = '';
    if (rrrRes.aturan && rrrRes.aturan.length) {
      ruleWarnings = rrrRes.aturan.map(a => `<div class="badge hold" style="display:block;margin-bottom:.4rem">⚠️ ${esc(a)}</div>`).join('');
    }
    
    let col3Html = `
      <section class="glass-panel" style="margin:0">
        <h3 class="sec">⚲ Analisis Risk / Reward</h3>
        ${ruleWarnings}
        <div class="between" style="align-items:center; margin-bottom:.6rem">
          <div style="font-size:1.6rem; font-weight:800">${esc(rrrRes.rrr)}</div>
          ${rrrRes.layak ? '<span class="badge buy">Layak ✓</span>' : '<span class="badge hold">&lt; 1:2 (Kurang Layak)</span>'}
        </div>
        
        <div class="crow"><span class="nm">Harga Beli OB1</span><b class="num">${fmt(rrrRes.harga_beli)}</b></div>
        <div class="crow"><span class="nm">Cut Loss (${clPrice ? 'Manual/ATR' : 'Default ' + riskPct + '%'})</span><b class="num pl-down">${fmt(rrrRes.cut_loss)} (${rrrRes.risk_pct}%)</b></div>
        <div class="crow"><span class="nm">Take Profit (+${targetProfitPct.toFixed(1)}%)</span><b class="num pl-up">${fmt(rrrRes.take_profit)} (${rrrRes.profit_pct}%)</b></div>
        <div class="crow"><span class="nm">Risk / Lembar</span><b class="num pl-down">-${fmt(rrrRes.risk_per_lembar)}</b></div>
        <div class="crow"><span class="nm">Reward / Lembar</span><b class="num pl-up">+${fmt(rrrRes.reward_per_lembar)}</b></div>
        
        ${atrMsg ? `<div class="badge hold" style="display:block;margin-top:.6rem;font-size:.7rem">${esc(atrMsg)}</div>` : ''}
        <p class="sub" style="margin-top:.4rem">${esc(rrrRes.catatan)}</p>
      </section>
    `;

    $('#active-plan-out').innerHTML = col1Html + col2Html + col3Html;

    // Render Profits Anywhere Guide
    if (broker === 'Profits Anywhere') {
      const cleanTicker = ticker.replace('.JK', '').replace('.jk', '').toUpperCase();
      const maxBuyLots = buyPrice > 0 ? Math.floor(rdnCash / (buyPrice * 100)) : 0;
      const sellLots = currentLots > 0 ? currentLots : (recommendedLots > 0 ? recommendedLots : 0);
      const sellAverage = pos ? pos.price : buyPrice;
      
      const buyFields = [
        { label: 'Price', value: buyPrice, underline: true },
        { label: 'Quantity (Lot)', value: recommendedLots, underline: true },
        { label: 'Cash Balance', value: fmt(rdnCash) },
        { label: 'Max Buy Quantity', value: `${maxBuyLots} lot(s)` },
        { label: 'Total Amount', value: fmt(recommendedVal) },
        { label: 'Haircut', value: '0' },
        { label: 'Last Traded Price', value: fmt(buyPrice) }
      ];

      const sellTpFields = [
        { label: 'Price', value: rrrRes.take_profit, underline: true },
        { label: 'Quantity (Lot)', value: sellLots, underline: true },
        { label: 'Balance', value: `${currentLots} lot(s)` },
        { label: 'Average', value: fmt(sellAverage) },
        { label: 'Total Amount', value: fmt(sellLots * 100 * rrrRes.take_profit) },
        { label: 'Haircut', value: '0' },
        { label: 'Last Traded Price', value: fmt(buyPrice) }
      ];

      const sellClFields = [
        { label: 'Price', value: rrrRes.cut_loss, underline: true },
        { label: 'Quantity (Lot)', value: sellLots, underline: true },
        { label: 'Balance', value: `${currentLots} lot(s)` },
        { label: 'Average', value: fmt(sellAverage) },
        { label: 'Total Amount', value: fmt(sellLots * 100 * rrrRes.cut_loss) },
        { label: 'Haircut', value: '0' },
        { label: 'Last Traded Price', value: fmt(buyPrice) }
      ];

      const buyMockupHtml = makePhintracoMockup('BUY', 'Profits Anywhere - BUY', '#38a169', buyFields, cleanTicker);
      const sellTpMockupHtml = makePhintracoMockup('SELL', 'Profits Anywhere - SELL (Take Profit)', '#e53e3e', sellTpFields, cleanTicker);
      const sellClMockupHtml = makePhintracoMockup('SELL', 'Profits Anywhere - SELL (Cut Loss)', '#e53e3e', sellClFields, cleanTicker);

      $('#phintraco-guide-out').innerHTML = buyMockupHtml + sellTpMockupHtml + sellClMockupHtml;
      $('#phintraco-guide-container').style.display = 'block';
    } else {
      $('#phintraco-guide-container').style.display = 'none';
    }

  } catch (err) {
    $('#active-plan-out').innerHTML = `<div class="empty" style="grid-column:span 3; color:var(--sell)">Terjadi kesalahan koneksi atau pengolahan API: ${esc(err.message)}</div>`;
    $('#phintraco-guide-container').style.display = 'none';
  }
}

function loadStrategi() {
  $('#strat-body').innerHTML = `
    <div class="panel-header"><h2>📚 Panduan Strategi Trading Harian Saham</h2></div>
    <p class="dim">Panduan pembelajaran komprehensif disadur dari buku <i>"Profit Konsisten Dari Trading Harian Saham"</i> oleh Henri H. Bahan belajar mandiri sebelum diintegrasikan ke dalam algoritma Aplikasi Saham Syariah.</p>

    <!-- SECTION 1 -->
    <div class="panel-header" style="margin-top:1.5rem"><h2>Bab 1 &amp; 2: Pengantar &amp; Dasar Trading</h2></div>
    
    <h4>1.1 Jenis-Jenis Trader Berdasarkan Waktu Eksekusi</h4>
    <p class="dim">Perbedaan gaya trading berdasarkan jangka waktu, kelebihan, kelemahan, dan target profit per transaksi:</p>
    <table style="width:100%; border-collapse:collapse; margin:1rem 0; font-size:.82rem;">
      <thead>
        <tr style="border-bottom:2px solid var(--line); text-align:left; color:#718096;">
          <th style="padding:.6rem;">Jenis</th>
          <th style="padding:.6rem;">Definisi</th>
          <th style="padding:.6rem;">Kelebihan</th>
          <th style="padding:.6rem;">Kelemahan</th>
          <th style="padding:.6rem; text-align:right;">Target Profit</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.6rem; font-weight:700; color:var(--buy)">⚡ Scalping</td>
          <td style="padding:.6rem;">Membuka &amp; menutup posisi dalam hitungan menit/detik memanfaatkan pergerakan kecil.</td>
          <td style="padding:.6rem;">Keuntungan cepat; tidak perlu memikirkan tren jangka panjang.</td>
          <td style="padding:.6rem;">Butuh fokus tinggi; biaya transaksi lebih besar karena frekuensi tinggi.</td>
          <td style="padding:.6rem; text-align:right; font-weight:700; color:var(--buy);">0.5% - 2.0%</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.6rem; font-weight:700; color:var(--brand)">☀️ Intraday</td>
          <td style="padding:.6rem;">Membeli dan menjual saham dalam satu hari perdagangan yang sama.</td>
          <td style="padding:.6rem;">Tidak ada risiko penahanan saham semalam; banyak peluang harian.</td>
          <td style="padding:.6rem;">Membutuhkan analisis teknikal intraday yang baik; rentan fluktuasi sesaat.</td>
          <td style="padding:.6rem; text-align:right; font-weight:700; color:var(--brand);">1.0% - 5.0%</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.6rem; font-weight:700; color:var(--warning)">🔄 Swing Trading</td>
          <td style="padding:.6rem;">Menahan saham selama beberapa hari hingga beberapa minggu mengikuti tren.</td>
          <td style="padding:.6rem;">Tidak perlu memantau pasar setiap saat; profit potensial jauh lebih besar.</td>
          <td style="padding:.6rem;">Rentan terhadap berita bursa semalam; modal tertahan lebih lama.</td>
          <td style="padding:.6rem; text-align:right; font-weight:700; color:var(--warning);">5.0% - 15.0%</td>
        </tr>
      </tbody>
    </table>

    <h4>1.2 Kamus Dasar Order Book</h4>
    <ul>
      <li><b>Bid (Harga Beli)</b>: Harga tertinggi yang bersedia dibayarkan oleh pembeli di pasar. Menunjukkan kekuatan minat beli.</li>
      <li><b>Ask / Offer (Harga Jual)</b>: Harga terendah yang bersedia diterima oleh penjual untuk melepas sahamnya.</li>
      <li><b>Last Price (Harga Terakhir)</b>: Harga transaksi terakhir yang terjadi (matched).</li>
      <li><b>Volume</b>: Jumlah total lot saham yang telah diperjualbelikan dalam periode tertentu.</li>
      <li><b>Lot</b>: Satuan transaksi saham di Indonesia (1 lot = 100 lembar saham).</li>
      <li><b>HAKA (Hajar Kanan)</b>: Membeli langsung di harga Offer agar pesanan langsung match tanpa antre.</li>
      <li><b>HAKI (Hajar Kiri)</b>: Menjual langsung di harga Bid agar saham langsung laku terjual tanpa antre.</li>
    </ul>

    <!-- SECTION 2 -->
    <div class="panel-header" style="margin-top:1.5rem"><h2>Bab 3: Membaca Pergerakan Pasar dengan Tape Reading</h2></div>
    <p class="dim">Metode analisis aliran pesanan secara real-time untuk membaca niat di balik transaksi dan melacak aktivitas pemain besar (*Big Players* / Bandar).</p>

    <h4>3.1 Ciri Akumulasi &amp; Distribusi Big Players</h4>
    <ul>
      <li><b>Fase Akumulasi (Pengumpulan Barang)</b>:
        <br>
        • Harga saham bergerak mendatar (*sideways*) dalam rentang sempit.
        <br>
        • Antrean Bid tebal terus diisi ulang meskipun ada banyak transaksi jual (*selling pressure*).
        <br>
        • Terjadi volume transaksi yang tinggi tanpa adanya kenaikan harga yang mencolok.
      </li>
      <li><b>Fase Distribusi (Pembagian Barang ke Publik)</b>:
        <br>
        • Harga saham merayap naik perlahan tetapi disertai penumpukan offer besar secara tiba-tiba.
        <br>
        • Volume transaksi sangat tinggi di harga atas, namun antrean Bid tidak aktif mendukung kenaikan harga.
      </li>
    </ul>

    <h4>3.2 Skenario Tape Reading &amp; Prediksi Arah Harga</h4>
    <table style="width:100%; border-collapse:collapse; margin:1rem 0; font-size:.82rem;">
      <thead>
        <tr style="border-bottom:2px solid var(--line); text-align:left; color:#718096;">
          <th style="padding:.5rem; width:5%;">No</th>
          <th style="padding:.5rem; width:30%;">Skenario Order Book</th>
          <th style="padding:.5rem; width:25%;">Interpretasi</th>
          <th style="padding:.5rem; width:30%;">Tanda / Ciri Utama</th>
          <th style="padding:.5rem; text-align:right; width:10%;">Prediksi</th>
        </tr>
      </thead>
      <tbody>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">1</td>
          <td style="padding:.5rem; font-weight:600;">Banyak Sell, Bid diisi terus</td>
          <td style="padding:.5rem;">Akumulasi Big Player.</td>
          <td style="padding:.5rem;">Bid terus bertambah meskipun volume offer meningkat; harga stabil.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--buy)">▲ Naik</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">2</td>
          <td style="padding:.5rem; font-weight:600;">Banyak Buy, Offer diisi terus</td>
          <td style="padding:.5rem;">Distribusi Big Player.</td>
          <td style="padding:.5rem;">Offer terus diisi volume besar; harga tertahan di resistance kunci.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--sell)">▼ Turun</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">3</td>
          <td style="padding:.5rem; font-weight:600;">Harga tertentu memiliki Bid besar</td>
          <td style="padding:.5rem;">Support kuat jangka pendek.</td>
          <td style="padding:.5rem;">Bid besar muncul berulang kali di level yang sama menahan penurunan.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--buy)">▲ Naik</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">4</td>
          <td style="padding:.5rem; font-weight:600;">Harga tertentu memiliki Offer besar</td>
          <td style="padding:.5rem;">Resistance kuat jangka pendek.</td>
          <td style="padding:.5rem;">Offer besar menghalangi kenaikan harga; volume transaksi tinggi di atap.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--sell)">▼ Turun</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">5</td>
          <td style="padding:.5rem; font-weight:600;">Penurunan tajam tanpa penurunan Bid</td>
          <td style="padding:.5rem;">Panic selling ritel diserap Big Player.</td>
          <td style="padding:.5rem;">Bid tetap stabil; volume di bid lebih besar dibanding offer.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--buy)">▲ Naik</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">6</td>
          <td style="padding:.5rem; font-weight:600;">Kenaikan tajam, Offer menipis cepat</td>
          <td style="padding:.5rem;">Potensi Breakout harga.</td>
          <td style="padding:.5rem;">Volume offer makin kecil; harga mulai bergerak naik lebih cepat.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--buy)">▲ Naik</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">7</td>
          <td style="padding:.5rem; font-weight:600;">Bid tebal mencurigakan tiba-tiba hilang</td>
          <td style="padding:.5rem;">Manipulasi order book (fake bid).</td>
          <td style="padding:.5rem;">Bid tebal mendadak dicabut sebelum tersentuh transaksi; harga anjlok.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--sell)">▼ Turun</td>
        </tr>
        <tr style="border-bottom:1px solid var(--line);">
          <td style="padding:.5rem;">8</td>
          <td style="padding:.5rem; font-weight:600;">Offer tebal di-Haka habis / dicabut</td>
          <td style="padding:.5rem;">Breakout terkonfirmasi kuat.</td>
          <td style="padding:.5rem;">Transaksi matched melonjak di offer diikuti kenaikan harga yang cepat.</td>
          <td style="padding:.5rem; text-align:right; font-weight:700; color:var(--buy)">▲ Naik</td>
        </tr>
      </tbody>
    </table>

    <!-- SECTION 3 -->
    <div class="panel-header" style="margin-top:1.5rem"><h2>Bab 5: Trading dengan Support &amp; Resistance Berbasis Volume</h2></div>
    <p class="dim">Konsep ini menggabungkan batas harga dengan volume transaksi riil di level tersebut menggunakan indikator <b>Volume Profile</b> untuk mendapatkan validasi level yang lebih akurat.</p>
    
    <h4>5.1 Komponen Volume Profile</h4>
    <ul>
      <li><b>POC (Point of Control)</b>: Level harga dengan volume transaksi tertinggi. Bertindak sebagai harga wajar (*fair value*) dan magnet harga tempat konsolidasi terjadi.</li>
      <li><b>Value Area (VA)</b>: Rentang harga tempat 70% volume perdagangan terjadi.
        <br>
        • <b>VAH (Value Area High)</b>: Batas atas Value Area (berfungsi sebagai resistance dinamis).
        <br>
        • <b>VAL (Value Area Low)</b>: Batas bawah Value Area (berfungsi sebagai support dinamis).
      </li>
    </ul>

    <h4>5.2 Panduan Strategi Volume Profile</h4>
    <ol>
      <li><b>Beli Dekat Support (VAL)</b>: Lakukan entry buy ketika harga menyentuh level VAL dan memperlihatkan sinyal pantulan (reversal candlestick).</li>
      <li><b>Target Profit di VAH / POC</b>: Tentukan target penjualan awal di dekat level POC atau batas atas VAH.</li>
      <li><b>Beli Saat Breakout &amp; Retest</b>: Jika harga menembus level VAH dengan volume besar, tunggu harga kembali turun menguji level VAH tersebut (*retest* yang ditandai diamond ◇ di aplikasi) sebelum membeli. Ini meminimalkan risiko terjebak *false breakout*.</li>
      <li><b>Hindari Tengah Value Area</b>: Jangan membuka posisi jika harga berada di tengah-tengah antara VAH dan VAL karena tidak memiliki arah tren yang jelas.</li>
    </ol>

    <!-- SECTION 4 -->
    <div class="panel-header" style="margin-top:1.5rem"><h2>Bab 6: Langkah Penyaringan (Screening) Saham Potensial</h2></div>
    <p class="dim">Parameter screening yang direkomendasikan untuk menyortir saham aktif yang siap untuk ditradingkan:</p>
    
    <div class="grid g-2" style="gap:1rem; margin-top:.5rem;">
      <div style="background:rgba(255,255,255,0.03); border:1px solid var(--line); border-radius:8px; padding:.8rem;">
        <h5 style="margin:0 0 .5rem 0; color:var(--brand)">🔎 Kriteria Teknis (TradingView)</h5>
        <ul style="font-size:.76rem; padding-left:1.1rem; margin:0;">
          <li><b>Market Cap</b>: &gt; 1T (menghindari saham gorengan)</li>
          <li><b>Average True Range (ATR)</b>: &gt; 1% (memastikan volatilitas cukup)</li>
          <li><b>RSI (14)</b>: Antara 30 s/d 70 (tidak overbought)</li>
          <li><b>Debt to Equity Ratio (DER)</b>: &lt; 1 (utang sehat)</li>
          <li><b>Return on Equity (ROE)</b>: &gt; 9% atau 10% (profitabilitas baik)</li>
          <li><b>Technical Rating</b>: Strong Buy / Buy</li>
        </ul>
      </div>
      <div style="background:rgba(255,255,255,0.03); border:1px solid var(--line); border-radius:8px; padding:.8rem;">
        <h5 style="margin:0 0 .5rem 0; color:var(--buy)">🐳 Kriteria Akumulasi (Stockbit Bandar)</h5>
        <ul style="font-size:.76rem; padding-left:1.1rem; margin:0;">
          <li><b>Harga vs MA200</b>: Price &ge; 0.1 &times; Price MA200</li>
          <li><b>Bandar Value vs MA20</b>: Bandar Value &gt; 1 &times; MA20</li>
          <li><b>Volume Harian</b>: Nilai transaksi harian &gt; 10 Miliar</li>
          <li><b>Bandar Accum/Dist</b>: Rating Accumulation &gt; 10</li>
          <li><b>Market Cap</b>: &gt; 200 Miliar</li>
        </ul>
      </div>
    </div>

    <!-- SECTION 5 -->
    <div class="panel-header" style="margin-top:1.5rem"><h2>🎁 Indikator Kustom: Volatility Insight Pro (Pine Script)</h2></div>
    <p class="dim">Sebagai bonus pembelajaran, Anda dapat memasang indikator kustom <b>Volatility Insight Pro</b> di akun TradingView Anda untuk menggabungkan Volume Profile, ATR, RSI, dan Moving Average secara otomatis.</p>
    
    <h4>Langkah Pemasangan Script:</h4>
    <ol>
      <li>Salin kode script Pine yang dapat diunduh dari link: <a href="https://bit.ly/VolatilityInsightPro" target="_blank" style="color:var(--brand); text-decoration:underline;">https://bit.ly/VolatilityInsightPro</a></li>
      <li>Buka chart saham apa saja di <b>TradingView</b>.</li>
      <li>Klik menu <b>Pine Editor</b> di bagian bawah layar.</li>
      <li>Hapus seluruh kode bawaan, tempel (*paste*) script yang telah disalin, lalu klik <b>Save</b> dengan nama "Volatility Insight Pro".</li>
      <li>Klik tombol <b>Add to Chart</b> untuk menampilkannya langsung di atas grafik harga.</li>
    </ol>

    <h4>Cara Menggunakan Parameter Indikator:</h4>
    <ul>
      <li><b>Volume Profile</b>: Menampilkan garis horizontal resistansi/dukungan volume terbesar. Berguna sebagai target jual atau beli.</li>
      <li><b>ATR (Average True Range)</b>: Digunakan secara internal untuk mengukur volatilitas. ATR yang tinggi memperkuat kekuatan sinyal beli.</li>
      <li><b>RSI (Relative Strength Index)</b>: Digunakan untuk mendeteksi area jenuh jual (RSI &lt; 30 = oversold/potensi beli) atau jenuh beli (RSI &gt; 70 = overbought/potensi jual).</li>
      <li><b>Rating Sinyal (1-5)</b>: Menampilkan kekuatan konfirmasi arah harga secara kumulatif. Rating 5 menunjukkan sinyal beli yang sangat kuat dan valid.</li>
      <li><b>Moving Average (MA)</b>: Digunakan sebagai filter tren utama. Arahkan posisi beli hanya jika harga bertahan di atas MA.</li>
    </ul>
  `;
}

/* ===================== PEMBELAJARAN ===================== */
let LEARNING_DATA = null;
let ACTIVE_MODULE = null;

async function loadLearning(forceRescan = false) {
  const container = $('.learning-nav-categories');
  container.innerHTML = '<div class="flex" style="padding:2rem"><span class="spin"></span><span class="dim">Memuat kurikulum…</span></div>';
  try {
    const d = await api('/api/learning/modules' + (forceRescan ? '?force_rescan=true' : ''));
    LEARNING_DATA = d;
    renderLearningSidebar();
  } catch (e) {
    container.innerHTML = '<div class="empty">Gagal memuat kurikulum: ' + e + '</div>';
  }
}

function renderLearningSidebar() {
  if (!LEARNING_DATA) return;
  const container = $('.learning-nav-categories');
  const catNames = {
    'dasar': '📖 1. Fondasi & Mindset',
    'teknikal': '🎯 2. Analisis Teknikal',
    'risk_management': '🛡️ 3. Money Management',
    'strategi': '🤖 4. Strategi & AI'
  };

  // Hitung progress
  $('#learn-pct').innerHTML = LEARNING_DATA.pct + '%';
  $('#learn-progress-bar').style.width = LEARNING_DATA.pct + '%';
  $('#learn-stat').innerHTML = `${LEARNING_DATA.completed_count} dari ${LEARNING_DATA.total_count} modul selesai`;

  // Group by category
  const groups = {};
  Object.keys(catNames).forEach(k => groups[k] = []);
  
  const activeModules = LEARNING_DATA.modules.filter(m => m.exists);
  activeModules.forEach(m => {
    if (groups[m.category]) {
      groups[m.category].push(m);
    }
  });

  let h = '';
  Object.keys(catNames).forEach(cat => {
    const mods = groups[cat];
    if (mods && mods.length) {
      h += `<div class="learning-cat-title">${catNames[cat]}</div>`;
      h += `<div class="learning-cat-group">`;
      mods.forEach(m => {
        const completed = LEARNING_DATA.progress[m.id] === true;
        const activeClass = (ACTIVE_MODULE && ACTIVE_MODULE.id === m.id) ? 'active' : '';
        const completedClass = completed ? 'completed' : '';
        
        h += `
          <div class="learning-card ${activeClass} ${completedClass}" onclick="openLearningModule('${m.id}')" data-mid="${m.id}" style="text-align:left">
            <div class="learning-card-check ${completed ? '' : 'pending'}">${completed ? '✓' : '○'}</div>
            <div style="flex:1">
              <div class="learning-card-title">${esc(m.title)}</div>
              <div class="learning-card-meta">
                <span>📄 ${m.pages} hlm</span>
                <span>💾 ${fmt(m.size_kb)} KB</span>
              </div>
            </div>
          </div>
        `;
      });
      h += `</div>`;
    }
  });

  container.innerHTML = h || '<div class="empty">Tidak ada modul PDF ditemukan di server Mac Mini.</div>';
}

function openLearningModule(id) {
  if (!LEARNING_DATA) return;
  const m = LEARNING_DATA.modules.find(x => x.id === id);
  if (!m) return;
  
  ACTIVE_MODULE = m;
  
  // Update sidebar active class
  document.querySelectorAll('.learning-card').forEach(c => {
    c.classList.remove('active');
    if (c.dataset.mid === id) c.classList.add('active');
  });

  $('#learn-viewer-empty').style.display = 'none';
  $('#learn-viewer-content').style.display = 'flex';

  $('#learn-title').innerHTML = esc(m.title);
  $('#learn-desc').innerHTML = esc(m.description);
  $('#learn-pages').innerHTML = m.pages;
  $('#learn-size').innerHTML = fmt(m.size_kb) + ' KB';
  $('#learn-complete-check').checked = LEARNING_DATA.progress[id] === true;

  // Set Iframe src
  $('#pdf-viewer-frame').src = `/api/learning/pdf/${id}`;

  // Render resources (Excel files)
  const resourcesList = $('#module-resources-list');
  const relatedRes = LEARNING_DATA.resources.filter(r => r.folder === m.folder && r.exists);
  
  if (relatedRes.length) {
    resourcesList.innerHTML = relatedRes.map(r => `
      <div class="resource-item">
        <div style="flex:1;padding-right:0.5rem;text-align:left">
          <div style="font-weight:600;font-size:0.72rem;color:var(--text)">${esc(r.title)}</div>
          <div class="mut" style="font-size:0.6rem;margin-top:0.15rem">${esc(r.description)}</div>
          <div class="mut" style="font-size:0.58rem;margin-top:0.1rem">💾 ${fmt(r.size_kb)} KB</div>
        </div>
        <a class="resource-btn" href="/api/learning/download/${r.id}" download>
          📥 Unduh
        </a>
      </div>
    `).join('');
  } else {
    resourcesList.innerHTML = '<p class="mut" style="font-size:0.7rem;text-align:center;margin-top:1rem">Tidak ada file Excel/template tambahan untuk bab ini.</p>';
  }
}

async function toggleLearningProgress() {
  if (!ACTIVE_MODULE || !LEARNING_DATA) return;
  const checked = $('#learn-complete-check').checked;
  try {
    const res = await post(`/api/learning/progress/${ACTIVE_MODULE.id}`, {completed: checked});
    LEARNING_DATA.progress = res.progress;
    LEARNING_DATA.pct = res.pct;
    LEARNING_DATA.completed_count = res.completed_count;
    LEARNING_DATA.total_count = res.total_count;
    
    // Rerender sidebar to update checkboxes and progress bars
    renderLearningSidebar();
    
    // Update card completion border/checkbox inline
    const card = document.querySelector(`.learning-card[data-mid="${ACTIVE_MODULE.id}"]`);
    if (card) {
      if (checked) {
        card.classList.add('completed');
        card.querySelector('.learning-card-check').classList.remove('pending');
        card.querySelector('.learning-card-check').innerHTML = '✓';
      } else {
        card.classList.remove('completed');
        card.querySelector('.learning-card-check').classList.add('pending');
        card.querySelector('.learning-card-check').innerHTML = '○';
      }
    }

    toast(checked ? 'Modul selesai dipelajari! 🎓' : 'Status selesai dihapus.');
  } catch (e) {
    toast('Gagal memperbarui progres: ' + e);
    $('#learn-complete-check').checked = !checked; // revert
  }
}


/* ===================== BSJP ===================== */
let _bsjpCandidates = [];
let _bsjpAutoRefresh = null;

function rp(n){ try{ return 'Rp '+Number(n).toLocaleString('id-ID'); } catch(e){ return '—'; } }
function pct(n,plus=true){ if(n===null||n===undefined) return '—'; const s=Number(n).toFixed(2)+'%'; return plus&&n>0?'+'+s:s; }

async function loadBSJPSession() {
  try {
    const s = await api('/api/bsjp/status');
    const dot = $('#bsjp-dot');
    const lbl = $('#bsjp-session-label');
    const aksi = $('#bsjp-session-aksi');
    const time = $('#bsjp-session-time');
    if(dot){ dot.className = 'bsjp-dot ' + (s.sesi||'closed'); }
    if(lbl) lbl.textContent = s.label || '—';
    if(aksi) aksi.textContent = s.aksi || '';
    if(time) time.textContent = s.waktu_server || '';
  } catch(e) {}
}

async function runBSJP() {
  const btn = $('#bsjp-scan-btn');
  const force = $('#bsjp-force')?.checked || false;
  if(btn){ btn.textContent = '⏳ Memindai…'; btn.disabled = true; }
  document.getElementById('bsjp-cnt-kandidat').textContent = '…';
  document.getElementById('bsjp-cnt-beli').textContent = '…';
  document.getElementById('bsjp-cnt-jual').textContent = '…';
  document.getElementById('bsjp-buy-table').innerHTML = '<div class="empty"><span class="spin"></span> Memindai saham syariah…</div>';
  document.getElementById('bsjp-sell-table').innerHTML = '<div class="empty"><span class="spin"></span> Mengecek posisi portofolio…</div>';

  try {
    await loadBSJPSession();
    const [cands, sells] = await Promise.all([
      api(`/api/bsjp/candidates?limit=20${force?'&force=true':''}`),
      api('/api/bsjp/sell-signals')
    ]);

    _bsjpCandidates = cands.candidates || [];
    const sellSignals = sells.signals || [];

    // Update summary
    document.getElementById('bsjp-cnt-kandidat').textContent = _bsjpCandidates.length;
    document.getElementById('bsjp-cnt-beli').textContent = cands.sinyal_kuat || 0;
    document.getElementById('bsjp-cnt-jual').textContent = sells.sinyal_jual || 0;

    // Render buy table
    renderBSJPBuyTable(_bsjpCandidates);

    // Render sell table
    renderBSJPSellTable(sellSignals);

    // Populate advisor ticker dropdown
    const advSel = $('#bsjp-adv-ticker');
    if(advSel && _bsjpCandidates.length > 0){
      advSel.innerHTML = _bsjpCandidates.map(c =>
        `<option value="${c.ticker}">${c.ticker}${c.buy_signal?' ✅':''}</option>`
      ).join('');
    }

    // Setup auto-refresh jika sesi aktif
    if(cands.sesi?.aktif){
      if(!_bsjpAutoRefresh){
        _bsjpAutoRefresh = setInterval(runBSJP, 5 * 60 * 1000); // tiap 5 menit
        toast('Auto-refresh aktif tiap 5 menit (sesi aktif).');
      }
    } else {
      if(_bsjpAutoRefresh){ clearInterval(_bsjpAutoRefresh); _bsjpAutoRefresh = null; }
    }

  } catch(e) {
    document.getElementById('bsjp-buy-table').innerHTML = `<div class="empty">Gagal memuat: ${esc(String(e))}</div>`;
  } finally {
    if(btn){ btn.textContent = '▶ Scan Sekarang'; btn.disabled = false; }
  }
}

function renderBSJPBuyTable(candidates) {
  const el = document.getElementById('bsjp-buy-table');
  if(!candidates || !candidates.length){
    el.innerHTML = '<div class="empty">Tidak ada kandidat BSJP saat ini. Coba saat sesi pre-closing (15:45–16:00).</div>';
    return;
  }
  const header = `<div class="bsjp-row header">
    <span>Ticker</span><span>IEP (est.)</span><span>CP Kemarin</span>
    <span>Gap IEP-CP</span><span>Skor</span><span>TV Signal</span><span>Aksi</span>
  </div>`;
  const rows = candidates.map(c => {
    const signal = c.buy_signal;
    const gapStr = c.gap_iep_cp_pct !== null && c.gap_iep_cp_pct !== undefined
      ? `<span style="color:${c.gap_iep_cp_pct>0?'var(--buy)':'var(--sell)'};">${pct(c.gap_iep_cp_pct)}</span>`
      : '<span class="mut">—</span>';
    const badge = signal
      ? '<span class="bsjp-badge-kuat">✅ BELI KUAT</span>'
      : '<span class="bsjp-badge-tahan">⏸ Pantau</span>';
    const scoreBar = `<div>${c.bsjp_score}</div><div class="bsjp-score-bar"><div class="bsjp-score-fill" style="width:${c.bsjp_score}%"></div></div>`;
    const recColor = c.rec_tv==='STRONG BUY'||c.rec_tv==='BUY' ? 'var(--buy)' : c.rec_tv==='NEUTRAL'?'var(--dim)':'var(--sell)';
    return `<div class="bsjp-row ${signal?'signal-strong':'signal-weak'}" style="cursor:pointer" onclick="selectBSJPAdvisor('${c.ticker}')">
      <span class="tkr">${esc(c.ticker)}</span>
      <span class="num">${c.iep ? rp(c.iep) : '—'}</span>
      <span class="num mut">${c.cp ? rp(c.cp) : '—'}</span>
      <span>${gapStr}</span>
      <span>${scoreBar}</span>
      <span style="color:${recColor};font-weight:700;font-size:.78rem">${esc(c.rec_tv||'—')}</span>
      <span>${badge}</span>
    </div>`;
  }).join('');
  el.innerHTML = `<div style="border:1px solid var(--border);border-radius:10px;overflow:hidden">${header}${rows}</div>
    <p class="sub" style="margin:.5rem 0 0">Klik baris untuk analisa Advisor BSJP. IEP = estimasi dari TradingView (proksi harga pre-closing).</p>`;
}

function renderBSJPSellTable(signals) {
  const el = document.getElementById('bsjp-sell-table');
  if(!signals || !signals.length){
    el.innerHTML = '<div class="empty">Tidak ada posisi portofolio aktif untuk BSJP. Tambahkan posisi di tab Portofolio.</div>';
    return;
  }
  const header = `<div class="bsjp-sell-row header">
    <span>Ticker</span><span>CP Kemarin</span><span>IEP Pagi</span>
    <span>Gap</span><span>Lot</span><span>Status / Aksi</span>
  </div>`;
  const rows = signals.map(s => {
    const sell = s.sell_signal;
    const gapStr = s.gap_pct !== null && s.gap_pct !== undefined
      ? `<span style="color:${s.gap_pct>0?'var(--buy)':'var(--sell)'};">${pct(s.gap_pct)}</span>`
      : '—';
    const statusEl = sell
      ? `<span style="color:var(--buy);font-weight:700">✅ JUAL 08:45–09:00</span>`
      : `<span class="mut">⏸ Tahan (IEP ≤ CP)</span>`;
    return `<div class="bsjp-sell-row ${sell?'sell-now':''}">
      <span class="tkr">${esc(s.ticker)}</span>
      <span class="num">${s.cp_kemarin ? rp(s.cp_kemarin) : '—'}</span>
      <span class="num">${s.iep_pagi ? rp(s.iep_pagi) : '—'}</span>
      <span>${gapStr}</span>
      <span>${s.lots||'—'} lot</span>
      <span>${statusEl}</span>
    </div>`;
  }).join('');
  el.innerHTML = `<div style="border:1px solid var(--border);border-radius:10px;overflow:hidden">${header}${rows}</div>`;
}

function selectBSJPAdvisor(ticker) {
  const sel = $('#bsjp-adv-ticker');
  if(sel) sel.value = ticker;
  document.getElementById('bsjp-advisor-sec')?.scrollIntoView({behavior:'smooth',block:'start'});
}

async function runBSJPAdvisor() {
  const ticker = $('#bsjp-adv-ticker')?.value;
  if(!ticker){ toast('Pilih ticker dulu.'); return; }
  const out = document.getElementById('bsjp-advisor-out');
  out.innerHTML = '<div class="empty"><span class="spin"></span> Menyusun analisa BSJP (Gemini / lokal)…</div>';
  try {
    const r = await api(`/api/bsjp/advisor/${encodeURIComponent(ticker)}`);
    if(!r.enabled){
      out.innerHTML = `<div class="empty mut">${esc(r.message||'Advisor tidak aktif.')}</div>`;
      return;
    }
    if(r.error){
      out.innerHTML = `<div class="empty" style="color:var(--sell)">${esc(r.error)}</div>`;
      return;
    }
    const v = r.verdict || {};
    const recClass = {BELI_KUAT:'beli-kuat',BELI_HATI:'beli-hati',TAHAN:'tahan',HINDARI:'hindari'}[v.rekomendasi] || 'tahan';
    const recColor = {BELI_KUAT:'var(--buy)',BELI_HATI:'var(--hold)',TAHAN:'var(--brand)',HINDARI:'var(--sell)'}[v.rekomendasi] || 'var(--dim)';
    const verdictHtml = v.rekomendasi ? `
      <div class="bsjp-verdict ${recClass}">
        <div class="bsjp-verdict-head">
          <span class="bsjp-verdict-label" style="color:${recColor}">${esc(v.rekomendasi)} — Keyakinan: ${esc(v.keyakinan||'—')}</span>
          ${v.risiko_utama ? `<span class="badge sell" style="font-size:.7rem">${esc(v.risiko_utama)}</span>` : ''}
        </div>
        ${(v.entry_pre_closing||v.target_pre_opening||v.stop_loss) ? `
          <div class="bsjp-verdict-plan">
            <div class="bsjp-verdict-plan-item">
              <span class="bsjp-verdict-plan-lbl">Entry Pre-Closing</span>
              <span class="bsjp-verdict-plan-val" style="color:var(--buy)">${v.entry_pre_closing?rp(v.entry_pre_closing):'—'}</span>
            </div>
            <div class="bsjp-verdict-plan-item">
              <span class="bsjp-verdict-plan-lbl">Target Pre-Opening</span>
              <span class="bsjp-verdict-plan-val" style="color:var(--buy)">${v.target_pre_opening?rp(v.target_pre_opening):'—'}</span>
            </div>
            <div class="bsjp-verdict-plan-item">
              <span class="bsjp-verdict-plan-lbl">Stop Loss</span>
              <span class="bsjp-verdict-plan-val" style="color:var(--sell)">${v.stop_loss?rp(v.stop_loss):'—'}</span>
            </div>
          </div>
        ` : ''}
      </div>` : '';
    out.innerHTML = `
      <div class="glass-panel ai-box" style="margin-top:.5rem">
        <div class="between" style="margin-bottom:.5rem">
          <h3 class="sec" style="margin:0;color:#a99bff">🤖 Analisa BSJP — ${esc(ticker)}</h3>
          <span class="mut" style="font-size:.7rem">${esc(r.model||'')}</span>
        </div>
        ${verdictHtml}
        <div class="ai-text">${mdb(r.analisa||'')}</div>
      </div>`;
  } catch(e) {
    out.innerHTML = `<div class="empty" style="color:var(--sell)">Gagal: ${esc(String(e))}</div>`;
  }
}

async function sendBSJPTelegram() {
  toast('Mengirim alert BSJP ke Telegram…');
  try {
    const r = await fetch('/api/bsjp/alert', {method:'POST'}).then(x=>x.json());
    if(r.telegram?.ok) toast('✅ Alert BSJP terkirim ke Telegram!');
    else toast('⚠️ Telegram gagal: ' + JSON.stringify(r.telegram));
  } catch(e) { toast('Error: ' + e); }
}

/* ===================== INIT ===================== */
function refreshAll(){ loadMarket(); loadUniverse(); _loaded.cmd=false; toast('Data pasar disegarkan.'); }
(async()=>{
  loadMarket(); loadUniverse(); loadPedoman(); loadStrategi(); loadEngines(); loadPortfolio();
  try{ const dc=await api('/api/disclaimer');
    $('#disc').innerHTML=`<b>Disclaimer:</b> ${esc(dc.disclaimer)}<br><br><b>Acuan:</b> ${dc.acuan.map(esc).join(' · ')}`;
  }catch(e){}
  runDecision(false, {fromInit: true, refresh: false});
  // Auto-load Radar Kontradiksi saat Dashboard dibuka (ditunda agar Pusat Keputusan
  // & kartu dashboard ter-render dulu; guard _loaded.cc cegah pemuatan ganda).
  setTimeout(()=>{ if(!_loaded.cc) loadCrossCheck(); }, 2500);
})();
