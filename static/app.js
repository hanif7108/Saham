/* Sharia Trading Assistant v2 - Frontend */

document.addEventListener('DOMContentLoaded', () => {
    // ---------- Theme Toggle ----------
    const root = document.documentElement;
    const btnTheme = document.getElementById('btn-theme');
    const savedTheme = localStorage.getItem('sta-theme') || 'dark';
    root.setAttribute('data-theme', savedTheme);
    btnTheme.textContent = savedTheme === 'dark' ? '🌙' : '☀️';
    btnTheme.addEventListener('click', () => {
        const cur = root.getAttribute('data-theme');
        const next = cur === 'dark' ? 'light' : 'dark';
        root.setAttribute('data-theme', next);
        localStorage.setItem('sta-theme', next);
        btnTheme.textContent = next === 'dark' ? '🌙' : '☀️';
        // Re-render charts kalau modal terbuka
        if (state.priceChart) renderCharts(state.lastChartData);
    });

    // ---------- DOM ----------
    const btnRefresh = document.getElementById('btn-refresh');
    const btnBuildMaster = document.getElementById('btn-build-master');
    const tbodyPortfolio = document.getElementById('tbody-portfolio');
    const listProspects = document.getElementById('list-prospects');

    const btnAddStock = document.getElementById('btn-add-stock');
    const formAddStock = document.getElementById('add-stock-form');
    const btnSubmitStock = document.getElementById('btn-submit-stock');
    const btnCancelStock = document.getElementById('btn-cancel-stock');
    const inpTicker = document.getElementById('inp-ticker');
    const inpHarga = document.getElementById('inp-harga');
    const inpLot = document.getElementById('inp-lot');

    const statPositions = document.getElementById('stat-positions');
    const statPnl = document.getElementById('stat-pnl');
    const statProspects = document.getElementById('stat-prospects');
    const statMaster = document.getElementById('stat-master');
    const cacheInfo = document.getElementById('cache-info');
    const linkClearCache = document.getElementById('link-clear-cache');

    // Modal
    const modal = document.getElementById('modal-detail');
    const modalClose = document.getElementById('modal-close');
    const modalTitle = document.getElementById('modal-title');
    const modalMeta = document.getElementById('modal-meta');
    const fundDetail = document.getElementById('fund-detail');
    const techDetail = document.getElementById('tech-detail');
    const jalur7Detail = document.getElementById('jalur7-detail');
    const btnRunBacktest = document.getElementById('btn-run-backtest');
    const backtestResult = document.getElementById('backtest-result');

    const modalRec = document.getElementById('modal-recommendation');
    const btnRecClose = document.getElementById('modal-rec-close');
    const predVerdictCard = document.getElementById('pred-verdict-card');

    function openRecommendationModal(e) {
        if (e) {
            e.stopPropagation();
            e.preventDefault();
        }
        if (modalRec) {
            modalRec.classList.remove('hidden');
        }
    }

    if (btnRecClose) {
        btnRecClose.addEventListener('click', (e) => {
            e.stopPropagation();
            modalRec.classList.add('hidden');
        });
    }

    if (predVerdictCard) {
        predVerdictCard.addEventListener('click', openRecommendationModal);
    }

    window.addEventListener('click', (e) => {
        if (modalRec && e.target === modalRec) {
            modalRec.classList.add('hidden');
        }
    });

    const state = {
        priceChart: null,
        rsiChart: null,
        currentTicker: null,
        lastChartData: null,
        goldChart: null,
        goldHistoryData: null,
        goldPredictionHorizon: '1d',
        silverChart: null,
        silverHistoryData: null,
        dinarChart: null,
        dinarHistoryData: null,
        dinarPredictionHorizon: '1d',
    };

    // ---------- Decision Center ----------
    const verdictBanner = document.getElementById('verdict-banner');
    const listSell = document.getElementById('list-sell');
    const listBuy = document.getElementById('list-buy');
    const countSell = document.getElementById('count-sell');
    const countBuy = document.getElementById('count-buy');
    const countHold = document.getElementById('count-hold');
    const holdInfo = document.getElementById('hold-info');
    const btnRefreshDecisions = document.getElementById('btn-refresh-decisions');

    btnRefreshDecisions.addEventListener('click', loadDecisions);

    function loadDecisions() {
        verdictBanner.innerHTML = '<span class="loading">Menghitung rekomendasi...</span>';
        listSell.innerHTML = '';
        listBuy.innerHTML = '';
        const listHold = document.getElementById('list-hold');
        if (listHold) listHold.innerHTML = '';

        fetch('/api/decisions')
            .then(r => r.json())
            .then(d => {
                // Verdict banner
                verdictBanner.textContent = d.summary.verdict || '–';

                // Counts
                countSell.textContent = d.summary.n_sell;
                countBuy.textContent = d.summary.n_buy;
                countHold.textContent = d.summary.n_hold;
                holdInfo.textContent = `${d.summary.n_hold} emiten portofolio dalam status HOLD — tidak ada aksi diperlukan saat ini.`;

                // SELL list
                if (d.sell.length === 0) {
                    listSell.innerHTML = '<p style="color:var(--text-secondary); font-size:0.85rem;">Tidak ada saham yang perlu dijual hari ini.</p>';
                } else {
                    d.sell.forEach(item => listSell.appendChild(makeDecisionCard(item)));
                }

                // BUY list
                if (d.buy.length === 0) {
                    listBuy.innerHTML = '<p style="color:var(--text-secondary); font-size:0.85rem;">Tidak ada peluang beli kuat hari ini. Wait and see.</p>';
                } else {
                    d.buy.forEach(item => listBuy.appendChild(makeDecisionCard(item)));
                }

                // HOLD list
                if (listHold) {
                    if (d.hold.length === 0) {
                        listHold.innerHTML = '<p style="color:var(--text-secondary); font-size:0.85rem;">Tidak ada saham portofolio dalam status HOLD hari ini.</p>';
                    } else {
                        d.hold.forEach(item => listHold.appendChild(makeDecisionCard(item)));
                    }
                }
            })
            .catch(err => {
                verdictBanner.textContent = `Error: ${err.message}`;
            });
    }

    function makeDecisionCard(item) {
        const card = document.createElement('div');
        const urgClass = (item.urgency || 'MEDIUM').toLowerCase();
        card.className = `decision-card ${urgClass}`;

        // Baris harga untuk rekomendasi BELI (harga beli / target / stop)
        let priceRow = '';
        const det = item.details || {};
        if (item.action === 'BUY' && det.entry_price) {
            const rp = v => 'Rp ' + Number(v).toLocaleString('id-ID');
            priceRow = `
            <div class="price-row">
                <span class="price-chip entry">Beli ±${rp(det.entry_price)}</span>
                ${det.target_price ? `<span class="price-chip target">🎯 ${rp(det.target_price)}</span>` : ''}
                ${det.stop_price ? `<span class="price-chip stop">🛑 ${rp(det.stop_price)}</span>` : ''}
            </div>`;
        }

        card.innerHTML = `
            <div class="ticker-line">
                <strong>${item.ticker}</strong>
                <span class="urgency-tag ${item.urgency}">${item.urgency}</span>
            </div>
            <div class="reason">${item.reason}</div>
            ${priceRow}
            <div class="next-step">→ ${item.next_step}</div>
        `;
        card.addEventListener('click', () => openModal(item.ticker));
        return card;
    }

    // ---------- Modal ----------
    function openModal(ticker) {
        state.currentTicker = ticker;
        modal.classList.remove('hidden');
        modalTitle.textContent = ticker;
        modalMeta.textContent = 'Memuat...';
        fundDetail.innerHTML = '<div class="loading">Loading...</div>';
        techDetail.innerHTML = '<div class="loading">Loading...</div>';
        jalur7Detail.innerHTML = '<div class="loading">Loading...</div>';
        backtestResult.innerHTML = '';
    }

    function deleteStock(ticker) {
        if (!confirm(`Yakin menghapus ${ticker}?`)) return;
        fetch(`/api/portfolio/${ticker}`, {method: 'DELETE'})
            .then(r => r.json())
            .then(d => { if (d.success) fetchPortfolio(); });
    }

    // ---------- Init ----------
    loadDecisions();
    fetchAll();
    loadBrokerPortfolio();
    updateCacheStats();

    // ---------- Events ----------
    btnRefresh.addEventListener('click', fetchAll);

    // Alert button
    const btnAlerts = document.getElementById('btn-alerts');
    btnAlerts.addEventListener('click', () => {
        btnAlerts.textContent = 'Scanning...';
        btnAlerts.disabled = true;
        fetch('/api/alerts/scan', {method: 'POST'})
            .then(r => r.json())
            .then(d => {
                btnAlerts.textContent = `🔔 Alert (${d.n_alerts})`;
                btnAlerts.disabled = false;
                if (d.n_alerts === 0) {
                    alert('Tidak ada alert aktif. Pasar tenang.');
                    return;
                }
                let msg = `${d.n_alerts} alert terdeteksi:\n\n`;
                d.alerts.forEach(a => {
                    msg += `• [${a.severity.toUpperCase()}] ${a.message}\n`;
                });
                alert(msg);
            });
    });

    // Telegram button
    const btnTelegram = document.getElementById('btn-telegram');
    btnTelegram.addEventListener('click', () => {
        // Cek status dulu
        fetch('/api/telegram/status').then(r => r.json()).then(s => {
            if (!s.configured) {
                alert('Telegram belum dikonfigurasi.\n\n' +
                      'Set environment variables:\n' +
                      '  TELEGRAM_BOT_TOKEN=...\n' +
                      '  TELEGRAM_CHAT_ID=...\n\n' +
                      'Lihat panduan setup di file modules/telegram_notify.py');
                return;
            }
            const choice = prompt(
                'Kirim ke Telegram:\n' +
                '  1 = Test message\n' +
                '  2 = Rekomendasi hari ini\n' +
                '  3 = Ringkasan portfolio\n' +
                '\nKetik angka:',
                '2'
            );
            if (!choice) return;
            const url = choice === '1' ? '/api/telegram/test'
                      : choice === '3' ? '/api/telegram/send_portfolio'
                      : '/api/telegram/send_decisions';
            btnTelegram.textContent = 'Sending...';
            btnTelegram.disabled = true;
            fetch(url, {method: 'POST'}).then(r => r.json()).then(d => {
                btnTelegram.textContent = '✈️ Telegram';
                btnTelegram.disabled = false;
                if (d.ok) {
                    alert('✓ Berhasil dikirim ke Telegram');
                } else {
                    alert('✗ Gagal: ' + (d.error || JSON.stringify(d)));
                }
            });
        });
    });

    // Export button
    const btnExport = document.getElementById('btn-export');
    btnExport.addEventListener('click', () => {
        const fmt = confirm('OK = Excel (XLSX)\nCancel = PDF') ? 'xlsx' : 'pdf';
        btnExport.textContent = 'Generating...';
        btnExport.disabled = true;
        // Trigger download via window.open
        const url = `/api/export/${fmt}`;
        window.open(url, '_blank');
        setTimeout(() => {
            btnExport.textContent = '📥 Export';
            btnExport.disabled = false;
        }, 2000);
    });

    btnBuildMaster.addEventListener('click', () => {
        btnBuildMaster.textContent = 'Memproses...';
        btnBuildMaster.disabled = true;
        fetch('/api/build_master', {method: 'POST'})
            .then(r => r.json())
            .then(d => {
                alert(d.message || 'Proses gagal.');
                btnBuildMaster.textContent = '⚙️ Update Master';
                btnBuildMaster.disabled = false;
            });
    });

    btnAddStock.addEventListener('click', () => formAddStock.classList.remove('hidden'));
    btnCancelStock.addEventListener('click', () => formAddStock.classList.add('hidden'));

    btnSubmitStock.addEventListener('click', () => {
        const payload = {
            ticker: inpTicker.value.trim().toUpperCase(),
            harga: parseFloat(inpHarga.value),
            lot: parseInt(inpLot.value)
        };
        fetch('/api/portfolio', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        }).then(r => r.json()).then(d => {
            if (d.success) {
                inpTicker.value = '';
                inpHarga.value = '';
                inpLot.value = '';
                formAddStock.classList.add('hidden');
                fetchPortfolio();
            } else {
                alert('Gagal menambahkan saham: ' + (d.error || ''));
            }
        });
    });

    modalClose.addEventListener('click', closeModal);
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
    });

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            document.querySelector(`[data-tab-pane="${tab}"]`).classList.add('active');
        });
    });

    btnRunBacktest.addEventListener('click', runBacktest);

    // ---------- All Stocks Ranking ----------
    const btnLoadAll = document.getElementById('btn-load-all');
    const selSector = document.getElementById('sel-sector');
    const selMinScore = document.getElementById('sel-min-score');
    const selSort = document.getElementById('sel-sort');
    const tbodyAll = document.getElementById('tbody-all');
    const allStats = document.getElementById('all-stats');

    btnLoadAll.addEventListener('click', loadAllStocks);
    selSector.addEventListener('change', loadAllStocks);
    selMinScore.addEventListener('change', loadAllStocks);
    selSort.addEventListener('change', loadAllStocks);

    function loadAllStocks() {
        const params = new URLSearchParams({
            sort_by: selSort.value,
            sector: selSector.value,
            min_score: selMinScore.value
        });
        tbodyAll.innerHTML = '<tr><td colspan="9" class="text-center loading">Memindai 75 emiten... (~5 detik)</td></tr>';
        allStats.textContent = '';
        fetch(`/api/all_stocks?${params}`)
            .then(r => r.json())
            .then(d => {
                // Populate sector dropdown (sekali saja, kalau belum)
                if (selSector.options.length <= 1 && d.sectors) {
                    d.sectors.forEach(s => {
                        const o = document.createElement('option');
                        o.value = s;
                        o.textContent = s;
                        selSector.appendChild(o);
                    });
                }

                tbodyAll.innerHTML = '';
                if (!d.stocks || d.stocks.length === 0) {
                    tbodyAll.innerHTML = '<tr><td colspan="9" class="text-center">Tidak ada emiten yang cocok dengan filter</td></tr>';
                    allStats.textContent = `0 emiten`;
                    return;
                }

                allStats.textContent = `${d.total} emiten ditampilkan • Sort: ${d.sort_by}`;

                d.stocks.forEach((s, idx) => {
                    const rankClass = idx < 3 ? 'rank-badge top3' : 'rank-badge';
                    const rsiColor = (s.rsi >= 70) ? 'var(--color-sell)' : (s.rsi <= 30 ? 'var(--color-buy)' : '');
                    const maStr = s.ma_cross === 'GOLDEN' ? '🟢 Golden'
                                : s.ma_cross === 'DEATH'  ? '🔴 Death'
                                : '–';
                    // Badge "data terbatas" bila indikator MA50/MACD belum reliabel
                    const limitedBadge = (s.reliable === false)
                        ? ` <span class="badge-limited" title="Data harga terbatas (${s.data_points || '?'} bar) — MA50/MACD belum reliabel">⚠ data terbatas</span>`
                        : '';

                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><span class="${rankClass}">${idx + 1}</span></td>
                        <td><strong>${s.ticker}</strong></td>
                        <td><small>${s.sector || '–'}</small></td>
                        <td>${formatRp(s.current_price || 0)}</td>
                        <td>${s.stars} <small>(${s.fundamental_score}/${s.fundamental_max})</small></td>
                        <td style="color:${rsiColor}; font-weight:600;">${s.rsi || '–'}</td>
                        <td><span class="tech-badge ${techCss(s.technical_signal)}">${s.technical_signal || '–'}</span>${limitedBadge}</td>
                        <td><small>${maStr}</small></td>
                        <td><span class="badge ${s.css_class} rec-trigger" style="cursor:pointer;" title="Klik untuk penjelasan">${s.final_signal}</span></td>
                    `;
                    tr.addEventListener('click', () => openModal(s.ticker));
                    
                    const recTrigger = tr.querySelector('.rec-trigger');
                    if (recTrigger) {
                        recTrigger.addEventListener('click', openRecommendationModal);
                    }
                    
                    tbodyAll.appendChild(tr);
                });
            })
            .catch(err => {
                tbodyAll.innerHTML = `<tr><td colspan="9" class="text-center">Error: ${err.message}</td></tr>`;
            });
    }

    linkClearCache.addEventListener('click', (e) => {
        e.preventDefault();
        if (!confirm('Hapus semua cache?')) return;
        fetch('/api/cache/clear', {method: 'POST'})
            .then(() => updateCacheStats());
    });

    // ---------- Functions ----------
    function fetchAll() {
        const btnKomoditas = document.getElementById('main-tab-btn-komoditas');
        const btnTop5 = document.getElementById('main-tab-btn-top5');
        const btnPortfolio = document.getElementById('main-tab-btn-portfolio');
        const btnSaham = document.getElementById('main-tab-btn-saham');
        if (btnKomoditas && btnKomoditas.classList.contains('active')) {
            loadCommodityData(true);
        } else if (btnTop5 && btnTop5.classList.contains('active')) {
            loadTop5Recommendations(true);
        } else if (btnPortfolio && btnPortfolio.classList.contains('active')) {
            loadBrokerPortfolio();
        } else {
            // Tab Dashboard / Saham — refresh dashboard + tabel detail
            if (btnSaham && btnSaham.classList.contains('active')) {
                loadDashboard();
            }
            fetchPortfolio();
            fetchProspects();
        }
    }

    // ============================================================
    // DASHBOARD TRADING SYARIAH — agregat halaman utama
    // ============================================================
    function rupiah(n) {
        if (n === null || n === undefined || isNaN(n)) return '–';
        const abs = Math.abs(n);
        if (abs >= 1e9) return `Rp ${(n / 1e9).toFixed(2)} M`;
        if (abs >= 1e6) return `Rp ${(n / 1e6).toFixed(2)} Jt`;
        if (abs >= 1e3) return `Rp ${(n / 1e3).toFixed(0)} rb`;
        return `Rp ${Math.round(n).toLocaleString('id-ID')}`;
    }

    function pctFmt(v, withSign = false) {
        if (v === null || v === undefined || isNaN(v)) return '–';
        const s = withSign && v > 0 ? '+' : '';
        return `${s}${v.toFixed(2)}%`;
    }

    function loadDashboard() {
        const verdictEl = document.getElementById('dashboard-verdict');
        const tsEl = document.getElementById('dashboard-timestamp');
        const actionListEl = document.getElementById('dashboard-action-list');
        const actionCountEl = document.getElementById('dashboard-action-count');
        const allocBarsEl = document.getElementById('dashboard-alloc-bars');
        const allocActionEl = document.getElementById('dashboard-alloc-action');
        const allocSignalsEl = document.getElementById('dashboard-alloc-signals');
        const portfolioSummaryEl = document.getElementById('dashboard-portfolio-summary');
        const portfolioPnlEl = document.getElementById('dashboard-portfolio-pnl');
        const top5El = document.getElementById('dashboard-top5');
        const commoditiesEl = document.getElementById('dashboard-commodities');
        const alertsEl = document.getElementById('dashboard-alerts');
        const ihsgEl = document.getElementById('dashboard-ihsg-status');

        if (verdictEl) verdictEl.innerHTML = '<span class="loading">Menghitung rekomendasi harian…</span>';

        fetch('/api/dashboard')
            .then(r => r.json())
            .then(d => {
                // ----- Timestamp + freshness data harga -----
                if (tsEl) {
                    let tsText = d.timestamp ? `Update: ${d.timestamp.replace('T', ' ')}` : '–';
                    const fr = d.data_freshness;
                    if (fr && fr.label) {
                        const dot = fr.market_open ? '🟢' : '🌙';
                        const mktTxt = fr.market_open ? 'pasar buka' : 'pasar tutup';
                        tsText += `  •  ${dot} Data harga: ${fr.label} (${mktTxt})`;
                    }
                    tsEl.textContent = tsText;
                }

                // ----- Verdict harian (gabungan decision + allocation) -----
                const decisionVerdict = (d.action_plan && d.action_plan.verdict) || '';
                const allocVerdict = (d.allocation && d.allocation.verdict) || '';
                if (verdictEl) {
                    verdictEl.innerHTML = `
                        <div class="verdict-line decision-verdict">${decisionVerdict || 'Tidak ada sinyal hari ini.'}</div>
                        <div class="verdict-line alloc-verdict">${allocVerdict || ''}</div>
                    `;
                }

                // ----- IHSG status badge -----
                if (ihsgEl && d.ihsg) {
                    if (d.ihsg.ihsg_close && d.ihsg.ihsg_ma50) {
                        const delta = ((d.ihsg.ihsg_close - d.ihsg.ihsg_ma50) / d.ihsg.ihsg_ma50 * 100);
                        const arrow = delta >= 0 ? '🟢' : '🔴';
                        ihsgEl.textContent = `${arrow} IHSG ${d.ihsg.ihsg_close.toFixed(0)} (${pctFmt(delta, true)} vs MA50)`;
                    } else {
                        ihsgEl.textContent = 'IHSG data n/a';
                    }
                }

                // ----- Action plan -----
                if (actionListEl && d.action_plan) {
                    const acts = d.action_plan.top_actions || [];
                    const budget = d.action_plan.budget || null;
                    if (actionCountEl) {
                        actionCountEl.textContent = `${d.action_plan.n_sell || 0} SELL · ${d.action_plan.n_buy || 0} BUY`;
                    }

                    // Budget header (kalau ada)
                    let budgetHtml = '';
                    if (budget) {
                        budgetHtml = `
                            <div class="action-budget">
                                <small class="muted">
                                    Budget trading: <strong>${rupiah(budget.trading_fund_rp)}</strong>
                                    untuk ${budget.n_buy_slots} slot
                                    (≈ ${rupiah(budget.bid_fund_per_ticker_rp)}/ticker)
                                </small>
                            </div>
                        `;
                    }

                    if (acts.length === 0) {
                        actionListEl.innerHTML = budgetHtml + '<p class="muted">Tidak ada aksi prioritas tinggi. HOLD semua.</p>';
                    } else {
                        const itemsHtml = acts.map(a => {
                            const cls = a.action === 'SELL' ? 'sell' : (a.action === 'BUY' ? 'buy' : 'hold');
                            const urgency = a.urgency || '';
                            const reason = a.reason || a.reasoning || '';
                            const s = a.sizing || {};
                            let sizingHtml = '';
                            if (s.lot > 0 && s.amount_rp > 0) {
                                if (a.action === 'BUY' && s.ob1_lot) {
                                    sizingHtml = `
                                        <div class="action-sizing buy">
                                            <div class="sizing-main">
                                                💰 <strong>Beli ${s.lot} lot</strong> @ Rp ${s.price.toLocaleString('id-ID')}
                                                = <strong>${rupiah(s.amount_rp)}</strong>
                                            </div>
                                            <div class="sizing-detail">
                                                <span class="ob-chip">Ob1: ${s.ob1_lot} lot @ Rp${s.ob1_price.toLocaleString('id-ID')} (${rupiah(s.ob1_amount_rp)})</span>
                                                <span class="ob-chip">Ob2: ${s.ob2_lot} lot @ Rp${s.ob2_price.toLocaleString('id-ID')}</span>
                                                <span class="ob-chip">Ob3: ${s.ob3_lot} lot @ Rp${s.ob3_price.toLocaleString('id-ID')}</span>
                                            </div>
                                        </div>
                                    `;
                                } else if (a.action === 'SELL') {
                                    sizingHtml = `
                                        <div class="action-sizing sell">
                                            <div class="sizing-main">
                                                💸 <strong>Jual ${s.lot} lot</strong> @ Rp ${s.price.toLocaleString('id-ID')}
                                                = terima <strong>${rupiah(s.amount_rp)}</strong>
                                            </div>
                                            ${s.note ? `<div class="sizing-detail muted">${s.note}</div>` : ''}
                                        </div>
                                    `;
                                }
                            }
                            return `
                                <div class="dashboard-action-item ${cls}">
                                    <div class="action-row">
                                        <span class="action-tag ${cls}">${a.action}</span>
                                        <strong class="action-ticker">${a.ticker}</strong>
                                        <span class="action-urgency">${urgency}</span>
                                    </div>
                                    <div class="action-reason">${reason}</div>
                                    ${sizingHtml}
                                </div>
                            `;
                        }).join('');
                        actionListEl.innerHTML = budgetHtml + itemsHtml;
                    }
                }

                // ----- Alokasi target -----
                if (allocBarsEl && d.allocation && d.allocation.target) {
                    const t = d.allocation.target;
                    const c = d.allocation.current || {};
                    const amounts = d.allocation.amounts || null;
                    if (allocActionEl) allocActionEl.textContent = d.allocation.action || '–';

                    // Header: total aset
                    let headerHtml = '';
                    if (amounts && amounts.total_asset_rp) {
                        headerHtml = `
                            <div class="alloc-total">
                                <small class="muted">Total Aset Anda:</small>
                                <strong>${rupiah(amounts.total_asset_rp)}</strong>
                            </div>
                        `;
                    }

                    const row = (label, key, color) => {
                        const tp = (t[key] || 0) * 100;
                        const cp = (c[key] || 0) * 100;
                        const dp = tp - cp;
                        const dpStr = dp === 0 ? '' : ` <span class="alloc-delta ${dp > 0 ? 'pos' : 'neg'}">(${dp > 0 ? '+' : ''}${dp.toFixed(1)}%)</span>`;
                        // Rupiah konkret
                        let amountHtml = '';
                        if (amounts) {
                            const tgtRp = amounts.target_rp[key] || 0;
                            const curRp = amounts.current_rp[key] || 0;
                            const gapRp = amounts.gap_rp[key] || 0;
                            const gapLabel = gapRp > 0
                                ? `<span class="gap-action pos">+ ${rupiah(gapRp)} (beli)</span>`
                                : (gapRp < 0
                                    ? `<span class="gap-action neg">${rupiah(gapRp)} (kurangi)</span>`
                                    : `<span class="gap-action">sudah pas</span>`);
                            amountHtml = `
                                <div class="alloc-rupiah">
                                    <div>Target: <strong>${rupiah(tgtRp)}</strong></div>
                                    <div>Saat ini: ${rupiah(curRp)}</div>
                                    <div>${gapLabel}</div>
                                </div>
                            `;
                        }
                        return `
                            <div class="alloc-row">
                                <div class="alloc-label">${label}</div>
                                <div class="alloc-bar-wrap">
                                    <div class="alloc-bar" style="width:${tp.toFixed(1)}%; background:${color}"></div>
                                    <div class="alloc-bar-current" style="width:${cp.toFixed(1)}%"></div>
                                </div>
                                <div class="alloc-value">
                                    <strong>${tp.toFixed(0)}% target</strong>
                                    <small class="muted">${cp.toFixed(0)}% saat ini${dpStr}</small>
                                    ${amountHtml}
                                </div>
                            </div>
                        `;
                    };
                    // 4-bucket render: Saham IDX, Saham US, Emas, Cash.
                    // Backward-compat: kalau backend lama (3-bucket), pakai key "saham" → render 1 baris.
                    const has4Bucket = 'saham_idx' in t || 'saham_us' in t;
                    allocBarsEl.innerHTML = headerHtml + (has4Bucket
                        ? (row('🇮🇩 Saham IDX', 'saham_idx', '#3b82f6')
                         + row('🇺🇸 Saham US',  'saham_us',  '#06b6d4')
                         + row('🪙 Emas',        'emas',      '#f59e0b')
                         + row('💵 Cash',        'cash',      '#10b981'))
                        : (row('📈 Saham', 'saham', '#3b82f6')
                         + row('🪙 Emas',  'emas',  '#f59e0b')
                         + row('💵 Cash',  'cash',  '#10b981'))
                    );

                    if (allocSignalsEl) {
                        const sigs = d.allocation.signals || [];
                        if (sigs.length === 0) {
                            allocSignalsEl.innerHTML = '<li class="muted">Tidak ada sinyal khusus — pakai baseline.</li>';
                        } else {
                            allocSignalsEl.innerHTML = sigs.map(s =>
                                `<li><strong>${s.name}</strong> <span class="muted">(${s.direction}, weight ${s.weight})</span><br><small>${s.detail}</small></li>`
                            ).join('');
                        }
                    }
                }

                // ----- Portfolio summary -----
                if (portfolioSummaryEl && d.portfolio) {
                    const p = d.portfolio;
                    const pnlCls = p.pnl_rp >= 0 ? 'pos' : 'neg';
                    if (portfolioPnlEl) {
                        portfolioPnlEl.textContent = `${rupiah(p.pnl_rp)} (${pctFmt(p.pnl_pct, true)})`;
                        portfolioPnlEl.className = `badge ${pnlCls}`;
                    }
                    portfolioSummaryEl.innerHTML = `
                        <div class="ps-row"><span>Total Nilai (saham + cash)</span><strong>${rupiah(p.total_rp)}</strong></div>
                        <div class="ps-row"><span>Holdings ${p.n_holdings} saham</span><strong>${rupiah(p.value_rp)}</strong></div>
                        <div class="ps-row"><span>Modal awal</span><strong>${rupiah(p.invested_rp)}</strong></div>
                        <div class="ps-row ${pnlCls}"><span>P/L unrealized</span><strong>${rupiah(p.pnl_rp)} (${pctFmt(p.pnl_pct, true)})</strong></div>
                        <div class="ps-row"><span>Cash broker</span><strong>${rupiah(p.cash_rp)}</strong></div>
                    `;
                }

                // ----- Top 5 saham -----
                if (top5El) {
                    const t5 = d.top5 || [];
                    if (t5.length === 0) {
                        top5El.innerHTML = '<li class="muted">Belum ada top picks hari ini.</li>';
                    } else {
                        top5El.innerHTML = t5.map(s => {
                            const sz = s.sizing || {};
                            const sizingHtml = sz.lot > 0
                                ? `<div class="t5-sizing">💰 ${sz.lot} lot @ Rp${(sz.price || 0).toLocaleString('id-ID')} = <strong>${rupiah(sz.amount_rp)}</strong></div>`
                                : '';
                            return `
                                <li>
                                    <div class="t5-main">
                                        <span class="t5-ticker">${s.ticker}</span>
                                        <span class="t5-signal">${s.final_signal || '–'}</span>
                                        <span class="t5-meta">F${s.fundamental_score || 0}/T${s.technical_score || 0} · ${(s.sector || '').slice(0, 14)}</span>
                                    </div>
                                    ${sizingHtml}
                                </li>
                            `;
                        }).join('');
                    }
                }

                // ----- Komoditas (emas, perak, dinar) -----
                if (commoditiesEl && d.commodities) {
                    const com = d.commodities;
                    const g = com.gold || {};
                    const s = com.silver || {};
                    const di = com.dinar || {};

                    const card = (icon, label, price, unit, signal, sigCls, sizingNote) => `
                        <div class="commodity-mini">
                            <div class="cm-head"><span class="cm-icon">${icon}</span><span class="cm-label">${label}</span></div>
                            <div class="cm-price">${price !== null && price !== undefined ? rupiah(price) : '–'}<small> ${unit}</small></div>
                            <div class="cm-signal ${sigCls}">${signal}</div>
                            ${sizingNote ? `<div class="cm-sizing">${sizingNote}</div>` : ''}
                        </div>
                    `;
                    const goldSigCls = (g.signal || '').includes('BUY') ? 'buy' : (g.signal || '').includes('SELL') ? 'sell' : 'hold';
                    const goldSizing = (g.sizing && g.sizing.note) ? g.sizing.note : '';
                    commoditiesEl.innerHTML =
                        card('🥇', 'Emas', g.price_idr_per_gram, '/gr', `${g.signal || '–'}${g.rsi !== null && g.rsi !== undefined ? ` · RSI ${g.rsi}` : ''}`, goldSigCls, goldSizing) +
                        card('🥈', 'Perak Antam', (s.antam_buy_idr_per_gram || s.spot_idr_per_gram), '/gr', s.trend_arrow ? `Trend ${s.trend_arrow}` : 'HOLD', 'hold', '') +
                        card('🪙', 'Dinar KR',  (di.sell_idr || di.buy_idr), '/keping', di.trend_arrow ? `Trend ${di.trend_arrow}` : 'HOLD', 'hold', '');
                }

                // ----- Alerts -----
                if (alertsEl) {
                    const alerts = d.alerts || [];
                    if (alerts.length === 0) {
                        alertsEl.innerHTML = '<li class="muted">Tidak ada alert aktif hari ini.</li>';
                    } else {
                        alertsEl.innerHTML = alerts.slice(0, 6).map(a => {
                            const sevCls = a.severity === 'high' ? 'high' : (a.severity === 'medium' ? 'medium' : 'low');
                            return `<li class="alert-mini sev-${sevCls}"><strong>${a.ticker || '–'}</strong> · ${a.message || a.type}</li>`;
                        }).join('');
                        if (d.alerts_count && d.alerts_count > 6) {
                            alertsEl.innerHTML += `<li class="muted">+ ${d.alerts_count - 6} alert lain…</li>`;
                        }
                    }
                }
            })
            .catch(err => {
                console.error('[dashboard] load failed', err);
                if (verdictEl) verdictEl.innerHTML = `<span class="text-negative">Gagal memuat dashboard: ${err.message}</span>`;
            });
    }
    window.loadDashboard = loadDashboard;

    // Wire up refresh button
    const btnRefreshDashboard = document.getElementById('btn-refresh-dashboard');
    if (btnRefreshDashboard) btnRefreshDashboard.addEventListener('click', loadDashboard);

    // Initial load
    setTimeout(loadDashboard, 100);

    // ============================================================
    // PEGADAIAN TRING — Emas Digital
    // ============================================================
    function loadPegadaianPortfolio() {
        const card = document.getElementById('card-plat-pegadaian');
        if (!card) return; // section belum ada di DOM

        // Set tanggal default hari ini
        const tglEl = document.getElementById('pgd-tanggal');
        if (tglEl && !tglEl.value) {
            tglEl.value = new Date().toISOString().slice(0, 10);
        }

        // Fetch current price untuk pre-fill harga
        fetch('/api/pegadaian/current_price')
            .then(r => r.json())
            .then(d => {
                const px = d.price_per_gram || 0;
                const priceDisplay = document.getElementById('pegadaian-current-price-display');
                if (priceDisplay) priceDisplay.textContent = `Harga current: Rp ${px.toLocaleString('id-ID')}/gr`;
                const hargaEl = document.getElementById('pgd-harga');
                if (hargaEl && !hargaEl.value) hargaEl.placeholder = `auto-fill: ${px.toLocaleString('id-ID')}`;
                window._pegadaian_current_price = px;
            })
            .catch(() => {});

        // Fetch portfolio summary + transactions
        fetch('/api/pegadaian/portfolio')
            .then(r => r.json())
            .then(d => {
                // Update card di Platform Breakdown
                const gramEl = document.getElementById('pegadaian-gram');
                const valEl = document.getElementById('pegadaian-emas-val');
                const cashEl = document.getElementById('pegadaian-cash');
                const avgEl = document.getElementById('pegadaian-avg-price');
                const pnlRpEl = document.getElementById('pegadaian-pnl-rp');
                const pnlPctEl = document.getElementById('pegadaian-pnl-pct');

                if (gramEl) gramEl.textContent = `${(d.total_gram || 0).toFixed(4)} gram`;
                if (valEl) valEl.textContent = rupiah(d.current_value_rp || 0);
                if (cashEl) cashEl.textContent = rupiah(d.saldo_rp || 0);
                if (avgEl) avgEl.textContent = `${rupiah(d.avg_buy_price || 0)}/gr`;
                if (pnlRpEl) {
                    pnlRpEl.textContent = `${rupiah(d.pnl_rp || 0)} (${pctFmt(d.pnl_pct, true)})`;
                    pnlRpEl.style.color = (d.pnl_rp >= 0) ? '#34d399' : '#f87171';
                }
                if (pnlPctEl) {
                    pnlPctEl.textContent = pctFmt(d.pnl_pct, true);
                    pnlPctEl.style.background = (d.pnl_pct >= 0) ? 'rgba(52,211,153,.18)' : 'rgba(248,113,113,.18)';
                    pnlPctEl.style.color = (d.pnl_pct >= 0) ? '#6ee7b7' : '#fca5a5';
                }

                // Render tabel transaksi
                const tbody = document.getElementById('tbody-pegadaian-tx');
                if (tbody) {
                    const txs = d.transactions || [];
                    if (txs.length === 0) {
                        tbody.innerHTML = '<tr><td colspan="7" class="text-center" style="color:var(--text-secondary); padding: 1.5rem;">Belum ada transaksi.</td></tr>';
                    } else {
                        tbody.innerHTML = txs.map(t => {
                            const typeClass = (t.tipe === 'BUY' || t.tipe === 'TOPUP') ? 'buy' : 'sell';
                            const gramStr = (t.gram > 0) ? `${parseFloat(t.gram).toFixed(4)} gr` : '–';
                            const hargaStr = (t.harga_per_gram > 0) ? rupiah(t.harga_per_gram) : '–';
                            return `
                                <tr>
                                    <td>${t.tanggal}</td>
                                    <td><span class="status-pill status-${typeClass}">${t.tipe}</span></td>
                                    <td style="text-align:right;">${gramStr}</td>
                                    <td style="text-align:right;">${hargaStr}</td>
                                    <td style="text-align:right;">${rupiah(t.nominal_rp)}</td>
                                    <td style="font-size:0.8rem; color:var(--text-secondary);">${t.catatan || '–'}</td>
                                    <td><button class="btn text-btn btn-del-pgd" data-id="${t.id}" title="Hapus" style="color:#f87171;">🗑</button></td>
                                </tr>
                            `;
                        }).join('');
                        // Wire delete buttons
                        tbody.querySelectorAll('.btn-del-pgd').forEach(btn => {
                            btn.addEventListener('click', () => {
                                if (!confirm(`Hapus transaksi ${btn.dataset.id}?`)) return;
                                fetch(`/api/pegadaian/transactions/${btn.dataset.id}`, {method: 'DELETE'})
                                    .then(r => r.json())
                                    .then(res => {
                                        if (res.success) {
                                            loadPegadaianPortfolio();
                                            if (window.loadGlobalPortfolio) window.loadGlobalPortfolio();
                                            if (window.loadDashboard) window.loadDashboard();
                                        } else {
                                            alert('Gagal hapus: ' + (res.error || '?'));
                                        }
                                    });
                            });
                        });
                    }
                }
            })
            .catch(err => console.error('[pegadaian] load failed', err));
    }
    window.loadPegadaianPortfolio = loadPegadaianPortfolio;

    // Adjust form fields visibility berdasarkan tipe
    const pgdTipeEl = document.getElementById('pgd-tipe');
    if (pgdTipeEl) {
        const adjustFields = () => {
            const tipe = pgdTipeEl.value;
            const labelGram = document.getElementById('pgd-label-gram');
            const labelHarga = document.getElementById('pgd-label-harga');
            const gramInput = document.getElementById('pgd-gram');
            const hargaInput = document.getElementById('pgd-harga');
            const nominalInput = document.getElementById('pgd-nominal');
            if (tipe === 'TOPUP' || tipe === 'WITHDRAWAL') {
                if (labelGram) labelGram.style.display = 'none';
                if (labelHarga) labelHarga.style.display = 'none';
                if (gramInput) { gramInput.value = ''; gramInput.required = false; }
                if (hargaInput) { hargaInput.value = ''; hargaInput.required = false; }
                if (nominalInput) nominalInput.required = true;
            } else {
                if (labelGram) labelGram.style.display = '';
                if (labelHarga) labelHarga.style.display = '';
                if (gramInput) gramInput.required = true;
                if (hargaInput) {
                    hargaInput.required = true;
                    // Auto-fill kalau kosong
                    if (!hargaInput.value && window._pegadaian_current_price) {
                        hargaInput.value = window._pegadaian_current_price;
                    }
                }
                if (nominalInput) nominalInput.required = false;
            }
        };
        pgdTipeEl.addEventListener('change', adjustFields);
        adjustFields();

        // Auto-hitung nominal dari gram × harga
        const recompute = () => {
            const tipe = pgdTipeEl.value;
            if (tipe === 'BUY' || tipe === 'SELL') {
                const g = parseFloat(document.getElementById('pgd-gram').value) || 0;
                const h = parseFloat(document.getElementById('pgd-harga').value) || 0;
                const n = document.getElementById('pgd-nominal');
                if (g > 0 && h > 0 && n) n.value = Math.round(g * h);
            }
        };
        ['pgd-gram', 'pgd-harga'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.addEventListener('input', recompute);
        });
    }

    // Submit form
    const pgdForm = document.getElementById('form-pegadaian-tx');
    if (pgdForm) {
        pgdForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const msgEl = document.getElementById('pgd-form-msg');
            const payload = {
                tipe:     document.getElementById('pgd-tipe').value,
                tanggal:  document.getElementById('pgd-tanggal').value,
                gram:     parseFloat(document.getElementById('pgd-gram').value) || 0,
                harga_per_gram: parseFloat(document.getElementById('pgd-harga').value) || 0,
                nominal_rp: parseFloat(document.getElementById('pgd-nominal').value) || 0,
                fee_rp:   parseFloat(document.getElementById('pgd-fee').value) || 0,
                catatan:  document.getElementById('pgd-catatan').value || ''
            };
            fetch('/api/pegadaian/transactions', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            })
            .then(r => r.json())
            .then(res => {
                if (res.success) {
                    if (msgEl) {
                        msgEl.style.color = '#34d399';
                        msgEl.textContent = `✓ Tersimpan: ${res.transaction.id}`;
                    }
                    pgdForm.reset();
                    document.getElementById('pgd-tanggal').value = new Date().toISOString().slice(0, 10);
                    loadPegadaianPortfolio();
                    if (window.loadGlobalPortfolio) window.loadGlobalPortfolio();
                    if (window.loadDashboard) window.loadDashboard();
                } else {
                    if (msgEl) {
                        msgEl.style.color = '#f87171';
                        msgEl.textContent = '✗ ' + (res.error || 'Gagal simpan');
                    }
                }
            })
            .catch(err => {
                if (msgEl) {
                    msgEl.style.color = '#f87171';
                    msgEl.textContent = '✗ Error: ' + err.message;
                }
            });
        });
    }

    // Refresh button
    const btnRefreshPgd = document.getElementById('btn-refresh-pegadaian');
    if (btnRefreshPgd) btnRefreshPgd.addEventListener('click', loadPegadaianPortfolio);

    function fetchPortfolio() {
        tbodyPortfolio.innerHTML = '<tr><td colspan="8" class="text-center loading">Menarik data...</td></tr>';
        fetch('/api/portfolio')
            .then(r => r.json())
            .then(data => {
                tbodyPortfolio.innerHTML = '';
                statPositions.textContent = data.length;

                if (data.length === 0) {
                    tbodyPortfolio.innerHTML = '<tr><td colspan="8" class="text-center">Portofolio kosong. Tambahkan saham!</td></tr>';
                    statPnl.textContent = '–';
                    return;
                }

                let totalPnl = 0;
                data.forEach(item => {
                    totalPnl += item.pnl;
                    const tr = document.createElement('tr');
                    tr.innerHTML = `
                        <td><strong>${item.ticker}</strong><br><small style="color:var(--text-secondary);">${item.sector || ''}</small></td>
                        <td>${formatRp(item.harga_beli)}</td>
                        <td>${formatRp(item.sekarang)}</td>
                        <td class="${item.pnl >= 0 ? 'text-positive' : 'text-negative'}">${item.pnl >= 0 ? '+' : ''}${item.pnl}%</td>
                        <td>${item.stars} <small>(${item.fundamental_score}/${item.fundamental_max})</small></td>
                        <td><span class="tech-badge ${techCss(item.technical_signal)}">${item.technical_signal || '–'}</span></td>
                        <td><span class="badge ${item.status_class}">${item.aksi}</span></td>
                        <td><button class="btn delete" data-action="delete">Hapus</button></td>
                    `;
                    tr.addEventListener('click', (e) => {
                        if (e.target.dataset.action === 'delete') {
                            e.stopPropagation();
                            deleteStock(item.ticker);
                        } else {
                            openModal(item.ticker);
                        }
                    });
                    tbodyPortfolio.appendChild(tr);
                });

                statPnl.innerHTML = `<span class="${totalPnl/data.length >= 0 ? 'text-positive' : 'text-negative'}">${(totalPnl/data.length).toFixed(2)}%</span>`;
            });
    }

    function fetchProspects() {
        listProspects.innerHTML = '<div class="text-center loading">Memindai...</div>';
        fetch('/api/prospects')
            .then(r => r.json())
            .then(data => {
                listProspects.innerHTML = '';
                statProspects.textContent = data.length;

                if (data.length === 0) {
                    listProspects.innerHTML = '<div class="text-center" style="color:var(--text-secondary)">Tidak ada ledakan volume.<br>Wait and see.</div>';
                    return;
                }

                data.forEach(item => {
                    const div = document.createElement('div');
                    div.className = 'prospect-card';
                    div.innerHTML = `
                        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                            <h3>${item.ticker} <span style="font-size:0.8em; margin-left:6px;">${item.fundamental.stars}</span></h3>
                            <span class="badge ${item.combined.css_class} rec-trigger" style="cursor:pointer;" title="Klik untuk penjelasan">${item.combined.final_signal}</span>
                        </div>
                        <div class="prospect-details" style="margin-top:0.4rem;">
                            <p>${item.sector}</p>
                            <p>Volume: <strong style="color:var(--color-brand)">${item.volume_spike}x</strong> • Tech: ${item.technical.signal}</p>
                            <p>Score: ${item.fundamental.score}/${item.fundamental.max_score}</p>
                        </div>
                    `;
                    div.addEventListener('click', () => openModal(item.ticker));
                    
                    const recTrigger = div.querySelector('.rec-trigger');
                    if (recTrigger) {
                        recTrigger.addEventListener('click', openRecommendationModal);
                    }
                    
                    listProspects.appendChild(div);
                });
            });
    }

    function updateCacheStats() {
        fetch('/api/cache/stats')
            .then(r => r.json())
            .then(d => {
                cacheInfo.textContent = `cache: ${d.history_files} histori, ${d.info_files} info`;
                statMaster.textContent = (d.history_files > 0) ? '✓ Aktif' : 'Kosong';
            });
    }

    function deleteStock(ticker) {
        if (!confirm(`Yakin menghapus ${ticker}?`)) return;
        fetch(`/api/portfolio/${ticker}`, {method: 'DELETE'})
            .then(r => r.json())
            .then(d => { if (d.success) fetchPortfolio(); });
    }

    // ---------- Modal ----------
    function openModal(ticker) {
        state.currentTicker = ticker;
        modal.classList.remove('hidden');
        modalTitle.textContent = ticker;
        modalMeta.textContent = 'Memuat...';
        fundDetail.innerHTML = '<div class="loading">Loading...</div>';
        techDetail.innerHTML = '<div class="loading">Loading...</div>';
        jalur7Detail.innerHTML = '<div class="loading">Loading...</div>';
        backtestResult.innerHTML = '';

        fetch(`/api/signal/${ticker}`)
            .then(r => r.json())
            .then(d => {
                const e = d.evaluation;
                modalTitle.textContent = `${e.ticker} — ${e.name || ''}`;
                modalMeta.innerHTML = `
                    <strong>${e.sector}</strong> •
                    Harga: ${formatRp(e.current_price || 0)} •
                    <span class="badge ${e.combined.css_class} rec-trigger" style="cursor:pointer;" title="Klik untuk penjelasan">${e.combined.final_signal}</span>
                `;
                
                const recTrigger = modalMeta.querySelector('.rec-trigger');
                if (recTrigger) {
                    recTrigger.addEventListener('click', openRecommendationModal);
                }

                state.lastChartData = d.chart;
                renderCharts(d.chart);
                renderFundamental(e.fundamental);
                renderTechnical(e.technical);
                renderJalur7(e.technical.jalur7);
            });
    }

    function closeModal() {
        modal.classList.add('hidden');
        if (state.priceChart) { state.priceChart.destroy(); state.priceChart = null; }
        if (state.rsiChart)   { state.rsiChart.destroy(); state.rsiChart = null; }
    }

    function renderCharts(chart) {
        if (!chart || !chart.labels || chart.labels.length === 0) return;

        const isDark = root.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#94a3b8' : '#475569';
        const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(15,23,42,0.05)';

        // Destroy existing
        if (state.priceChart) state.priceChart.destroy();
        if (state.rsiChart)   state.rsiChart.destroy();

        const priceCtx = document.getElementById('chart-price').getContext('2d');
        state.priceChart = new Chart(priceCtx, {
            type: 'line',
            data: {
                labels: chart.labels,
                datasets: [
                    {label: 'Close', data: chart.close, borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,0.1)', borderWidth: 2, tension: 0.2, pointRadius: 0, fill: true},
                    {label: 'MA20', data: chart.ma20, borderColor: '#10b981', borderWidth: 1.5, tension: 0.2, pointRadius: 0, fill: false},
                    {label: 'MA50', data: chart.ma50, borderColor: '#f59e0b', borderWidth: 1.5, tension: 0.2, pointRadius: 0, fill: false},
                ]
            },
            options: {
                responsive: true,
                interaction: {mode: 'index', intersect: false},
                plugins: {
                    legend: {labels: {color: textColor}},
                    title: {display: true, text: 'Harga & Moving Average', color: textColor}
                },
                scales: {
                    x: {ticks: {color: textColor, maxRotation: 0, autoSkip: true, maxTicksLimit: 8}, grid: {color: gridColor}},
                    y: {ticks: {color: textColor}, grid: {color: gridColor}}
                }
            }
        });

        const rsiCtx = document.getElementById('chart-rsi').getContext('2d');
        state.rsiChart = new Chart(rsiCtx, {
            type: 'line',
            data: {
                labels: chart.labels,
                datasets: [
                    {label: 'RSI', data: chart.rsi, borderColor: '#a855f7', borderWidth: 2, tension: 0.2, pointRadius: 0, fill: false},
                    {label: 'Overbought 70', data: chart.labels.map(() => 70), borderColor: 'rgba(239,68,68,0.5)', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false},
                    {label: 'Oversold 30', data: chart.labels.map(() => 30), borderColor: 'rgba(16,185,129,0.5)', borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false}
                ]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {labels: {color: textColor}},
                    title: {display: true, text: 'RSI (14)', color: textColor}
                },
                scales: {
                    x: {ticks: {color: textColor, maxRotation: 0, autoSkip: true, maxTicksLimit: 8}, grid: {color: gridColor}},
                    y: {min: 0, max: 100, ticks: {color: textColor}, grid: {color: gridColor}}
                }
            }
        });
    }

    function renderFundamental(f) {
        let html = `
            <div class="metric-row"><span>Score</span><strong>${f.score} / ${f.max_score} ${f.stars}</strong></div>
            <div class="metric-row"><span>Label</span><span class="badge ${f.label === 'STRONG BUY' || f.label === 'BUY' ? 'buy' : (f.label === 'AVOID' ? 'sell' : 'hold')}">${f.label}</span></div>
            <h4 style="margin-top:1rem;">Lulus Kriteria</h4>
            <ul class="reason-list">${(f.reasons_pass || []).map(r => `<li class="reason-pass">${r}</li>`).join('') || '<li>–</li>'}</ul>
            <h4 style="margin-top:0.75rem;">Tidak Lulus</h4>
            <ul class="reason-list">${(f.reasons_fail || []).map(r => `<li class="reason-fail">${r}</li>`).join('') || '<li>–</li>'}</ul>
        `;
        fundDetail.innerHTML = html;
    }

    function renderTechnical(t) {
        const limitedRow = (t.reliable === false)
            ? `<div class="metric-row"><span>Reliabilitas</span><span class="badge-limited" title="MA50/MACD belum reliabel">⚠ data terbatas (${t.data_points || '?'} bar)</span></div>`
            : '';
        let html = `
            <div class="metric-row"><span>Sinyal</span><span class="tech-badge ${techCss(t.signal)}">${t.signal}</span></div>
            <div class="metric-row"><span>Score</span><strong>${t.score}</strong></div>
            <div class="metric-row"><span>RSI</span><strong>${t.rsi}</strong></div>
            <div class="metric-row"><span>MACD Hist</span><strong>${t.macd_hist}</strong></div>
            <div class="metric-row"><span>MA20 / MA50</span><strong>${t.ma20 ?? '–'} / ${t.ma50 ?? '–'}</strong></div>
            <div class="metric-row"><span>MA Cross</span><strong>${t.ma_cross ?? '–'}</strong></div>
            <div class="metric-row"><span>Volume Spike</span><strong>${t.volume_spike || '–'}x</strong></div>
            ${limitedRow}
            <h4 style="margin-top:1rem;">Catatan</h4>
            <ul class="reason-list">${(t.reasons || []).map(r => `<li class="reason-info">${r}</li>`).join('')}</ul>
        `;
        techDetail.innerHTML = html;
    }

    function renderJalur7(j) {
        if (!j || !j.signals) {
            jalur7Detail.innerHTML = '<p style="color:var(--text-secondary); font-size:0.85rem;">Data Jalur 7% tidak tersedia.</p>';
            return;
        }

        let html = `
            <div class="metric-row"><span>Verdict</span><strong style="color:var(--color-brand);">${j.verdict || '–'}</strong></div>
            <div class="metric-row"><span>Score</span><strong>${j.score} / ${j.max_score}</strong></div>
            
            <h4 style="margin-top:1.25rem; margin-bottom:0.75rem;">Checklist Sinyal Jalur 7%</h4>
        `;

        const sigs = [
            { id: 'breaker', name: '1. Sinyal Breaker (Breakout)', desc: 'Breakout 20-day high dengan body candle solid hijau dan volume transaksi tinggi.' },
            { id: 'kandang_kuda', name: '2. Sinyal Kandang Kuda (Konsolidasi)', desc: 'Konsolidasi rentang harga sempit dan stabil (sideways) dekat MA20.' },
            { id: 'shadow', name: '3. Sinyal Shadow (Lower Shadow Rejection)', desc: 'Penolakan harga turun ditandai lower shadow panjang berulang di area support.' },
            { id: 'swing_line', name: '4. Sinyal Swing Line (Tren Naik Sehat)', desc: 'Tren naik yang sehat, teratur, dan stabil bergerak di atas MA20.' }
        ];

        sigs.forEach(s => {
            const signalData = j.signals[s.id] || { pass: false, reason: 'Tidak aktif' };
            const pass = signalData.pass;
            const statusLabel = pass ? 'Lolos (Aktif)' : 'Tidak Aktif';
            const reason = signalData.reason || '–';

            html += `
                <div class="jalur7-signal-card" style="margin-bottom:0.75rem; padding:0.85rem; border-radius:8px; background:rgba(255,255,255,0.02); border:1px solid ${pass ? 'rgba(16,185,129,0.3)' : 'rgba(255,255,255,0.05)'};">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.4rem;">
                        <span style="font-weight:600; font-size:0.9rem; color:${pass ? 'var(--text-primary)' : 'var(--text-secondary)'};">${s.name}</span>
                        <span class="badge ${pass ? 'buy' : 'hold'}" style="font-size:0.75rem; padding:2px 8px;">${statusLabel}</span>
                    </div>
                    <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem; font-style:italic;">
                        ${s.desc}
                    </div>
                    <div style="font-size:0.8rem; color:${pass ? 'var(--color-buy)' : 'var(--text-secondary)'}; background:rgba(0,0,0,0.15); padding:6px 10px; border-radius:4px; line-height:1.4;">
                        ${pass ? '🟢 ' : '❌ '}${reason}
                    </div>
                </div>
            `;
        });

        jalur7Detail.innerHTML = html;
    }

    function runBacktest() {
        if (!state.currentTicker) return;
        backtestResult.innerHTML = '<div class="loading">Backtesting...</div>';
        fetch(`/api/backtest/${state.currentTicker}?period=1y`)
            .then(r => r.json())
            .then(d => {
                if (d.error) {
                    backtestResult.innerHTML = `<p>Error: ${d.error}</p>`;
                    return;
                }
                const m = d.metrics;
                let html = `
                    <div class="metric-row"><span>Total Return</span><strong class="${(m.total_return_pct || 0) >= 0 ? 'text-positive' : 'text-negative'}">${m.total_return_pct}%</strong></div>
                    <div class="metric-row"><span>N Trades</span><strong>${m.n_trades}</strong></div>
                    <div class="metric-row"><span>Win Rate</span><strong>${m.win_rate}%</strong></div>
                    <div class="metric-row"><span>Max Drawdown</span><strong class="text-negative">${m.max_dd_pct}%</strong></div>
                    <div class="metric-row"><span>Avg Holding</span><strong>${m.avg_holding} hari</strong></div>
                    <div class="metric-row"><span>Best / Worst</span><strong>${m.best_trade}% / ${m.worst_trade}%</strong></div>
                `;
                if (d.trades.length > 0) {
                    html += '<h4 style="margin-top:1rem;">Trade Log</h4>';
                    html += '<table style="width:100%; font-size:0.8rem;"><thead><tr><th>Entry</th><th>Exit</th><th>P/L</th><th>Hari</th><th>Alasan</th></tr></thead><tbody>';
                    d.trades.forEach(t => {
                        html += `<tr>
                            <td>${t.entry_date}<br><small>${formatRp(t.entry_price)}</small></td>
                            <td>${t.exit_date}<br><small>${formatRp(t.exit_price)}</small></td>
                            <td class="${t.pnl_pct >= 0 ? 'text-positive' : 'text-negative'}">${t.pnl_pct}%</td>
                            <td>${t.holding_days}</td>
                            <td><small>${t.reason}</small></td>
                        </tr>`;
                    });
                    html += '</tbody></table>';
                }
                backtestResult.innerHTML = html;
            });
    }

    function techCss(signal) {
        if (signal === 'BUY') return 'badge buy';
        if (signal === 'SELL') return 'badge sell';
        return 'badge hold';
    }

    function formatRp(n) {
        if (typeof n !== 'number') return '–';
        return n.toLocaleString('id-ID', {maximumFractionDigits: 2});
    }

    // ---------- Emas & Komoditas Tab Logic ----------
    let commodityDataLoaded = false;
    let globalCommodityData = null;

    // ---------- Top 5 Rekomendasi Tab Logic ----------
    let top5Loaded = false;
    let globalTop5Data = null;

    window.switchMainTab = function(tab) {
        const tabs = {
            'saham': { btnId: 'main-tab-btn-saham', contentId: 'main-tab-saham-content', onLoad: () => {
                // Fire kedua US card (Action Plan + Top 5) DULU (cepat & visible),
                // baru loadDashboard yang berat untuk IDX.
                if (window.loadDashboardUSCards) window.loadDashboardUSCards();
                if (window.loadDashboard) window.loadDashboard();
            } },
            'idxstock': { btnId: 'main-tab-btn-idxstock', contentId: 'main-tab-idxstock-content', onLoad: () => { if (window.loadIDXStockTab) window.loadIDXStockTab(); } },
            'usstock': { btnId: 'main-tab-btn-usstock', contentId: 'main-tab-usstock-content', onLoad: () => { if (window.loadUSStockTab) window.loadUSStockTab(); } },
            'komoditas': { btnId: 'main-tab-btn-komoditas', contentId: 'main-tab-komoditas-content', onLoad: loadCommodityData },
            'perakdinar': { btnId: 'main-tab-btn-perakdinar', contentId: 'main-tab-perakdinar-content', onLoad: loadSilverDinarData },
            'top5': { btnId: 'main-tab-btn-top5', contentId: 'main-tab-top5-content', onLoad: loadTop5Recommendations },
            'portfolio': { btnId: 'main-tab-btn-portfolio', contentId: 'main-tab-portfolio-content', onLoad: () => { if (window.loadGlobalPortfolio) window.loadGlobalPortfolio(); loadBrokerPortfolio(); if (window.loadPegadaianPortfolio) window.loadPegadaianPortfolio(); } },
            'tradersakti': { btnId: 'main-tab-btn-tradersakti', contentId: 'main-tab-tradersakti-content', onLoad: () => { if (window.initTraderSaktiHub) window.initTraderSaktiHub(); } },
            'rules': { btnId: 'main-tab-btn-rules', contentId: 'main-tab-rules-content' }
        };

        Object.keys(tabs).forEach(key => {
            const btn = document.getElementById(tabs[key].btnId);
            const content = document.getElementById(tabs[key].contentId);
            if (key === tab) {
                if (btn) btn.classList.add('active');
                if (content) content.classList.remove('hidden');
                if (tabs[key].onLoad) tabs[key].onLoad();
            } else {
                if (btn) btn.classList.remove('active');
                if (content) content.classList.add('hidden');
            }
        });
    };

    function loadCommodityData(force = false) {
        const spotCardsContainer = document.getElementById('spot-cards-container');
        const tbodySpotTable = document.getElementById('tbody-spot-table');
        const tbodyAntamPegadaian = document.getElementById('tbody-antam-pegadaian');
        const tbodyUbs = document.getElementById('tbody-ubs');
        const listPluangAssets = document.getElementById('list-pluang-assets');
        const tbodyKurs = document.getElementById('tbody-kurs');
        const timestampEl = document.getElementById('commodity-timestamp');

        // Set loading state
        spotCardsContainer.innerHTML = '<div class="text-center loading" style="grid-column: span 2;">Memuat data spot emas...</div>';
        tbodySpotTable.innerHTML = '<tr><td colspan="3" class="text-center loading">Memuat...</td></tr>';
        tbodyAntamPegadaian.innerHTML = '<tr><td colspan="3" class="text-center loading">Memuat...</td></tr>';
        tbodyUbs.innerHTML = '<tr><td colspan="3" class="text-center loading">Memuat...</td></tr>';
        listPluangAssets.innerHTML = '<div class="text-center loading">Memuat...</div>';
        tbodyKurs.innerHTML = '<tr><td colspan="3" class="text-center loading">Memuat...</td></tr>';
        timestampEl.textContent = 'Memperbarui...';

        const url = `/api/commodities${force ? '?refresh=1' : ''}`;

        fetch(url)
            .then(r => r.json())
            .then(data => {
                if (!data.ok) {
                    const err = data.error || 'Gagal mengambil data komoditas.';
                    spotCardsContainer.innerHTML = `<div class="text-center text-negative" style="grid-column: span 2;">Error: ${err}</div>`;
                    return;
                }

                globalCommodityData = data;
                commodityDataLoaded = true;

                // Render timestamp
                timestampEl.textContent = `Terakhir diperbarui: ${data.timestamp || '–'}`;

                // 1. Render Spot Gold Cards
                spotCardsContainer.innerHTML = '';
                if (data.gold_spot) {
                    // USD Card
                    if (data.gold_spot.usd && data.gold_spot.usd.length > 0) {
                        spotCardsContainer.appendChild(createSpotCard('Spot Emas Dunia (USD)', data.gold_spot.usd));
                    }
                    // IDR Card
                    if (data.gold_spot.idr && data.gold_spot.idr.length > 0) {
                        spotCardsContainer.appendChild(createSpotCard('Spot Emas Dunia (IDR)', data.gold_spot.idr));
                    }
                }
                if (spotCardsContainer.innerHTML === '') {
                    spotCardsContainer.innerHTML = '<div class="text-center" style="grid-column: span 2; color:var(--text-secondary)">Data spot tidak tersedia</div>';
                }

                // 2. Render Spot Detail Table
                tbodySpotTable.innerHTML = '';
                if (data.spot_table && data.spot_table.length > 0) {
                    data.spot_table.forEach(row => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><strong>${row.unit}</strong></td>
                            <td>${row.usd}</td>
                            <td>${row.idr}</td>
                        `;
                        tbodySpotTable.appendChild(tr);
                    });
                } else {
                    tbodySpotTable.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-secondary)">Data tidak tersedia</td></tr>';
                }

                // 3. Render Antam & Pegadaian Table
                tbodyAntamPegadaian.innerHTML = '';
                if (data.antam_pegadaian_table && data.antam_pegadaian_table.length > 0) {
                    data.antam_pegadaian_table.forEach(row => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><strong>${row.gram}</strong></td>
                            <td class="text-positive">${row.antam}</td>
                            <td class="text-positive">${row.pegadaian}</td>
                        `;
                        tbodyAntamPegadaian.appendChild(tr);
                    });
                } else {
                    tbodyAntamPegadaian.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-secondary)">Data tidak tersedia</td></tr>';
                }

                // 4. Render UBS Table
                tbodyUbs.innerHTML = '';
                if (data.ubs_table && data.ubs_table.length > 0) {
                    data.ubs_table.forEach(row => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><strong>${row.gram}</strong></td>
                            <td class="text-positive">${row.jual}</td>
                            <td class="text-positive">${row.beli}</td>
                        `;
                        tbodyUbs.appendChild(tr);
                    });
                } else {
                    tbodyUbs.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-secondary)">Data tidak tersedia</td></tr>';
                }

                // 5. Render Pluang Assets List
                listPluangAssets.innerHTML = '';
                if (data.pluang_assets && data.pluang_assets.length > 0) {
                    data.pluang_assets.forEach(asset => {
                        const isPositive = asset.change_pct && (asset.change_pct.startsWith('+') || !asset.change_pct.startsWith('-'));
                        const changeClass = isPositive ? 'text-positive' : 'text-negative';
                        const div = document.createElement('div');
                        div.className = 'pluang-asset-item';
                        div.innerHTML = `
                            <div class="asset-meta">
                                <div class="asset-header">
                                    <span class="asset-symbol">${asset.symbol}</span>
                                    <span class="asset-category">${asset.category}</span>
                                </div>
                                <span class="asset-name" title="${asset.name}">${asset.name}</span>
                            </div>
                            <span class="asset-change ${changeClass}">${asset.change_pct || '0.00%'}</span>
                        `;
                        listPluangAssets.appendChild(div);
                    });
                } else {
                    listPluangAssets.innerHTML = '<div class="text-center" style="color:var(--text-secondary)">Tidak ada data aset Pluang</div>';
                }

                // 6. Render Kurs Valas (Default: BI)
                const selKursBank = document.getElementById('sel-kurs-bank');
                if (selKursBank) {
                    switchBankKurs(selKursBank.value);
                }

                // 7. Load Gold History Chart & Prediction
                loadGoldHistoryChart();
                loadGoldPrediction(force);
            })
            .catch(err => {
                const errorMsg = `Gagal memuat data komoditas: ${err.message}`;
                spotCardsContainer.innerHTML = `<div class="text-center text-negative" style="grid-column: span 2;">${errorMsg}</div>`;
                tbodySpotTable.innerHTML = `<tr><td colspan="3" class="text-center text-negative">Error</td></tr>`;
                tbodyAntamPegadaian.innerHTML = `<tr><td colspan="3" class="text-center text-negative">Error</td></tr>`;
                tbodyUbs.innerHTML = `<tr><td colspan="3" class="text-center text-negative">Error</td></tr>`;
                listPluangAssets.innerHTML = `<div class="text-center text-negative">Error</div>`;
                tbodyKurs.innerHTML = `<tr><td colspan="3" class="text-center text-negative">Error</td></tr>`;
                timestampEl.textContent = 'Error';
            });
    }

    // ---------- Antam Gold Chart & Zoom Logic ----------
    function loadGoldHistoryChart() {
        const canvas = document.getElementById('chart-gold-history');
        if (!canvas) return;

        fetch('/api/gold/history')
            .then(r => r.json())
            .then(data => {
                if (!data || data.length === 0) {
                    console.error('No gold history data returned.');
                    return;
                }
                state.goldHistoryData = data;
                renderGoldChart('all'); // Default: Semua (1 tahun penuh)
            })
            .catch(err => console.error('Failed to load gold history:', err));
    }

    function loadGoldPrediction(force = false) {
        const predContent = document.getElementById('gold-pred-content');
        const predDate = document.getElementById('gold-pred-date');
        if (!predContent) return;

        predContent.innerHTML = '<div class="text-center loading" style="padding:1.5rem 0;">Menghitung data model...</div>';
        if (predDate) predDate.textContent = 'Menganalisis...';

        const horizon = state.goldPredictionHorizon || '1d';
        const url = `/api/gold/prediction?horizon=${horizon}${force ? '&refresh=1' : ''}`;

        fetch(url)
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    predContent.innerHTML = `<div class="text-center text-negative" style="padding:1rem 0;">Error: ${data.error || 'Gagal memuat prediksi'}</div>`;
                    if (predDate) predDate.textContent = 'Error';
                    return;
                }

                // Update accuracy badge
                const predAccuracy = document.getElementById('gold-pred-accuracy');
                if (predAccuracy) {
                    if (data.accuracy_pct !== undefined && data.accuracy_pct !== null) {
                        predAccuracy.innerHTML = `🎯 Akurasi: ${data.accuracy_pct.toFixed(2)}%`;
                        predAccuracy.style.display = 'inline-block';
                    } else {
                        predAccuracy.innerHTML = `🎯 Akurasi: Menunggu data`;
                        predAccuracy.style.display = 'inline-block';
                    }
                }

                if (predDate) {
                    const dateToday = new Date(data.date_today);
                    const daysOffset = data.horizon === '1w' ? 7 : 1;
                    dateToday.setDate(dateToday.getDate() + daysOffset);
                    const options = { year: 'numeric', month: 'short', day: 'numeric' };
                    predDate.textContent = `Target: ${dateToday.toLocaleDateString('id-ID', options)}`;
                }

                const fmt = (num) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(num);

                let agentRows = '';
                data.agents.forEach(agent => {
                    const isSellUp = agent.change_sell_pct >= 0;
                    const changeSellClass = isSellUp ? 'text-positive' : 'text-negative';
                    const changeSellIcon = isSellUp ? '▲' : '▼';
                    const changeSellSign = isSellUp ? '+' : '';

                    const isBuyUp = agent.change_buy_pct >= 0;
                    const changeBuyClass = isBuyUp ? 'text-positive' : 'text-negative';
                    const changeBuyIcon = isBuyUp ? '▲' : '▼';
                    const changeBuySign = isBuyUp ? '+' : '';

                    agentRows += `
                        <div style="padding:0.75rem 0; border-bottom:1px solid rgba(255,255,255,0.03); display:grid; grid-template-columns: 1.2fr 1fr 1fr; gap:0.5rem; align-items:center;">
                            <div style="font-weight:600; font-size:0.85rem; color:var(--text-primary);">${agent.name}</div>
                            <div>
                                <div style="font-size:0.85rem; font-weight:600; color:var(--text-primary);">${fmt(agent.predicted_sell)}</div>
                                <div class="${changeSellClass}" style="font-size:0.7rem; font-weight:500;">
                                    ${changeSellIcon} ${changeSellSign}${agent.change_sell_pct.toFixed(4)}%
                                </div>
                            </div>
                            <div>
                                <div style="font-size:0.85rem; font-weight:600; color:var(--text-primary);">${fmt(agent.predicted_buy)}</div>
                                <div class="${changeBuyClass}" style="font-size:0.7rem; font-weight:500;">
                                    ${changeBuyIcon} ${changeBuySign}${agent.change_buy_pct.toFixed(4)}%
                                </div>
                            </div>
                        </div>
                    `;
                });

                const driftClass = data.daily_drift >= 0 ? 'text-positive' : 'text-negative';
                const driftIcon = data.daily_drift >= 0 ? '▲' : '▼';
                const driftSign = data.daily_drift >= 0 ? '+' : '';

                // Build daily trajectory table & recommendations if 1w
                let trajectorySection = '';
                if (data.horizon === '1w' && data.weekly_trajectory) {
                    let trajRows = '';
                    data.weekly_trajectory.forEach(day => {
                        const dateFormatted = day.date.split('-').reverse().slice(0, 2).join('/');
                        trajRows += `
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.02); font-size:0.75rem;">
                                <td style="padding:0.4rem 0; font-weight:600; color:var(--text-primary);">${day.day_name} <span style="font-size:0.65rem; color:var(--text-secondary); font-weight:normal;">(${dateFormatted})</span></td>
                                <td style="padding:0.4rem 0;">
                                    <div style="font-weight:600; color:var(--text-primary);">${fmt(day.best_buy_agent.price)}</div>
                                    <div style="font-size:0.65rem; color:#06b6d4; font-weight:500;">${day.best_buy_agent.name.split(' ')[0]}</div>
                                </td>
                                <td style="padding:0.4rem 0;">
                                    <div style="font-weight:600; color:var(--text-primary);">${fmt(day.best_sell_agent.price)}</div>
                                    <div style="font-size:0.65rem; color:#f59e0b; font-weight:500;">${day.best_sell_agent.name.split(' ')[0]}</div>
                                </td>
                            </tr>
                        `;
                    });

                    const bestBuyDateFormatted = data.best_buy_day_info.date.split('-').reverse().slice(0, 2).join('/');
                    const bestSellDateFormatted = data.best_sell_day_info.date.split('-').reverse().slice(0, 2).join('/');

                    trajectorySection = `
                        <!-- Best Days Summary Badges -->
                        <div style="background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:0.75rem; margin-bottom:1.25rem;">
                            <div style="font-weight:700; font-size:0.75rem; color:var(--text-primary); margin-bottom:0.5rem; display:flex; align-items:center; gap:0.25rem;">
                                📅 Rekomendasi Hari Terbaik (1 Pekan)
                            </div>
                            <div style="display:flex; flex-direction:column; gap:0.5rem;">
                                <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem;">
                                    <span style="color:var(--text-secondary);">🛒 Hari Beli Terbaik:</span>
                                    <span style="font-weight:700; color:#06b6d4; text-align:right;">
                                        ${data.best_buy_day_info.day_name} (${bestBuyDateFormatted})<br>
                                        <span style="font-size:0.7rem; font-weight:500;">${data.best_buy_day_info.agent.split(' ')[0]} (${fmt(data.best_buy_day_info.price)})</span>
                                    </span>
                                </div>
                                <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem; border-top:1px dashed rgba(255,255,255,0.05); padding-top:0.5rem; margin-top:0.25rem;">
                                    <span style="color:var(--text-secondary);">💰 Hari Jual (Buyback) Terbaik:</span>
                                    <span style="font-weight:700; color:#f59e0b; text-align:right;">
                                        ${data.best_sell_day_info.day_name} (${bestSellDateFormatted})<br>
                                        <span style="font-size:0.7rem; font-weight:500;">${data.best_sell_day_info.agent.split(' ')[0]} (${fmt(data.best_sell_day_info.price)})</span>
                                    </span>
                                </div>
                            </div>
                        </div>

                        <!-- Trajectory Daily Grid -->
                        <div style="margin-bottom:1.25rem;">
                            <div style="font-weight:700; font-size:0.75rem; color:var(--text-primary); margin-bottom:0.5rem;">📅 Proyeksi Harian 1 Pekan</div>
                            <table style="width:100%; border-collapse:collapse; border:none;">
                                <thead>
                                    <tr style="border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.65rem; font-weight:700; color:var(--text-secondary); text-transform:uppercase; text-align:left; letter-spacing:0.5px;">
                                        <th style="padding-bottom:0.25rem;">Hari</th>
                                        <th style="padding-bottom:0.25rem;">Beli Terendah</th>
                                        <th style="padding-bottom:0.25rem;">Jual (Buyback)</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${trajRows}
                                </tbody>
                            </table>
                        </div>
                    `;
                }

                predContent.innerHTML = `
                    <div style="display:grid; grid-template-columns: 1fr 1fr; gap:0.75rem; margin-bottom:1.25rem;">
                        <div class="glass-panel" style="background:rgba(6, 182, 212, 0.03); border:1px solid rgba(6, 182, 212, 0.1); padding:0.75rem; border-radius:8px; display:flex; flex-direction:column; gap:0.25rem;">
                            <span style="font-size:0.7rem; color:var(--text-secondary); font-weight:600;">🛒 Agen Beli Terbaik</span>
                            <span style="font-size:0.8rem; font-weight:700; color:var(--text-primary); margin-top:0.1rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${data.best_buy_agent.name}</span>
                            <span style="font-size:0.9rem; font-weight:800; color:#06b6d4; margin-top:0.1rem;">${fmt(data.best_buy_agent.price)}</span>
                            <span style="font-size:0.6rem; color:var(--text-secondary);">(Jual Agen Terendah)</span>
                        </div>
                        <div class="glass-panel" style="background:rgba(245, 158, 11, 0.03); border:1px solid rgba(245, 158, 11, 0.1); padding:0.75rem; border-radius:8px; display:flex; flex-direction:column; gap:0.25rem;">
                            <span style="font-size:0.7rem; color:var(--text-secondary); font-weight:600;">💰 Agen Jual Terbaik</span>
                            <span style="font-size:0.8rem; font-weight:700; color:var(--text-primary); margin-top:0.1rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${data.best_sell_agent.name}</span>
                            <span style="font-size:0.9rem; font-weight:800; color:#f59e0b; margin-top:0.1rem;">${fmt(data.best_sell_agent.price)}</span>
                            <span style="font-size:0.6rem; color:var(--text-secondary);">(Buyback Tertinggi)</span>
                        </div>
                    </div>

                    <div style="padding-bottom:0.4rem; border-bottom:1px solid rgba(255,255,255,0.05); display:grid; grid-template-columns: 1.2fr 1fr 1fr; gap:0.5rem; font-size:0.7rem; font-weight:700; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.5px;">
                        <div>Agen Emas (100g)</div>
                        <div>Beli (Jual Agen)</div>
                        <div>Jual (Buyback)</div>
                    </div>

                    <div style="margin-bottom:1.25rem;">
                        ${agentRows}
                    </div>

                    ${trajectorySection}

                    <div style="background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.03); padding:0.6rem 0.75rem; border-radius:6px; font-size:0.7rem; color:var(--text-secondary); line-height:1.4;">
                        <div style="font-weight:600; color:var(--text-primary); margin-bottom:0.2rem; display:flex; justify-content:space-between;">
                            <span>📊 Statistik Prediksi ${data.horizon === '1w' ? 'H+5 (1 Pekan)' : 'H+1 (1 Hari)'}</span>
                            <span class="${driftClass}" style="font-weight:700;">
                                ${driftIcon} ${driftSign}${fmt(data.daily_drift * data.forecast_days)}/${data.horizon === '1w' ? 'pekan' : 'hari'}
                            </span>
                        </div>
                        Tren harian emas saat ini bergerak <strong class="${driftClass}">${data.daily_drift >= 0 ? 'bullish (naik)' : 'bearish (turun)'}</strong> dengan penyimpangan rata-rata 10 hari terakhir sebesar Rp ${new Intl.NumberFormat('id-ID').format(data.std_dev_10d)}. Nilai di atas diproyeksikan dengan menerapkan rasio premium brand fisik terhadap estimasi momentum spot penutupan ${data.horizon === '1w' ? 'pekan depan' : 'besok'}.
                    </div>
                `;
            })
            .catch(err => {
                console.error('Failed to load gold prediction:', err);
                predContent.innerHTML = `<div class="text-center text-negative" style="padding:1rem 0;">Error: ${err.message}</div>`;
                if (predDate) predDate.textContent = 'Error';
            });
    }

    window.switchGoldPredHorizon = function(horizon) {
        state.goldPredictionHorizon = horizon;
        
        const btn1d = document.getElementById('btn-gold-pred-1d');
        const btn1w = document.getElementById('btn-gold-pred-1w');
        if (btn1d && btn1w) {
            if (horizon === '1d') {
                btn1d.classList.add('active');
                btn1w.classList.remove('active');
            } else {
                btn1w.classList.add('active');
                btn1d.classList.remove('active');
            }
        }
        
        loadGoldPrediction(false);
    };

    function renderGoldChart(zoomRange) {
        const canvas = document.getElementById('chart-gold-history');
        if (!canvas || !state.goldHistoryData) return;

        let filteredData = state.goldHistoryData;
        if (zoomRange !== 'all') {
            const days = parseInt(zoomRange);
            if (!isNaN(days)) {
                filteredData = state.goldHistoryData.slice(-days);
            }
        }

        const labels = filteredData.map(item => item.date);
        const prices = filteredData.map(item => item.price);

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#94a3b8' : '#475569';
        const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(15,23,42,0.05)';

        if (state.goldChart) {
            state.goldChart.destroy();
        }

        const ctx = canvas.getContext('2d');
        state.goldChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Harga Emas Antam (Rp/gr)',
                    data: prices,
                    borderColor: '#f59e0b', // Gold Amber
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    borderWidth: 2,
                    tension: 0.15,
                    pointRadius: filteredData.length > 60 ? 0 : 3, // Hide points if too dense
                    pointHoverRadius: 5,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            color: textColor,
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 8
                        },
                        grid: {
                            color: gridColor
                        }
                    },
                    y: {
                        ticks: {
                            color: textColor,
                            callback: function(value, index, values) {
                                return 'Rp ' + new Intl.NumberFormat('id-ID', { maximumFractionDigits: 0 }).format(value);
                            }
                        },
                        grid: {
                            color: gridColor
                        }
                    }
                }
            }
        });
    }

    window.zoomGoldChart = function(range) {
        // Toggle active button style
        const buttons = {
            7: 'btn-gold-zoom-7d',
            30: 'btn-gold-zoom-30d',
            365: 'btn-gold-zoom-1y',
            'all': 'btn-gold-zoom-all'
        };

        Object.keys(buttons).forEach(key => {
            const btn = document.getElementById(buttons[key]);
            if (btn) {
                if (key.toString() === range.toString()) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            }
        });

        renderGoldChart(range);
    };

    function createSpotCard(title, items, label = 'Emas Spot') {
        const card = document.createElement('div');
        card.className = 'commodity-spot-card';
        
        let itemsHtml = '';
        items.forEach(item => {
            const isPositive = item.change && (item.change.startsWith('+') || item.change.startsWith('▲'));
            const changeClass = isPositive ? 'text-positive' : (item.change && (item.change.startsWith('-') || item.change.startsWith('▼')) ? 'text-negative' : 'text-secondary');
            itemsHtml += `
                <div class="spot-item">
                    <div class="spot-unit-label">
                        <span class="spot-unit-name">${label}</span>
                        <span class="spot-unit-desc">per ${item.unit || 'oz'}</span>
                    </div>
                    <div class="spot-price-info">
                        <span class="spot-price">${item.price}</span>
                        <span class="spot-change ${changeClass}">${item.change || '0.0%'}</span>
                    </div>
                </div>
            `;
        });

        card.innerHTML = `
            <span class="card-title">${title}</span>
            <div class="spot-items-list">
                ${itemsHtml}
            </div>
        `;
        return card;
    }

    // ---------- Perak & Dinar Tab Logic ----------
    let silverDinarDataLoaded = false;
    let globalSilverDinarData = null;

    function loadSilverDinarData(force = false) {
        const spotCards = document.getElementById('silver-spot-cards');
        const tbodySpot = document.getElementById('tbody-silver-spot');
        const tbodyAntam = document.getElementById('tbody-silver-antam');
        const tbodyDinar = document.getElementById('tbody-dinar-prices');
        const dinarDateLabel = document.getElementById('dinar-date-label');
        const perakTimestamp = document.getElementById('perak-timestamp');

        // Set Loading
        spotCards.innerHTML = '<div class="text-center loading" style="grid-column: span 2;">Memuat data spot perak...</div>';
        tbodySpot.innerHTML = '<tr><td colspan="3" class="text-center loading">Memuat...</td></tr>';
        tbodyAntam.innerHTML = '<tr><td colspan="2" class="text-center loading">Memuat...</td></tr>';
        tbodyDinar.innerHTML = '<tr><td colspan="3" class="text-center loading">Memuat...</td></tr>';
        dinarDateLabel.textContent = 'Memuat...';
        if (perakTimestamp) perakTimestamp.textContent = 'Memperbarui...';

        const url = `/api/silver-dinar/prices${force ? '?refresh=1' : ''}`;

        fetch(url)
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    const err = data.error || 'Gagal mengambil data Perak & Dinar.';
                    spotCards.innerHTML = `<div class="text-center text-negative" style="grid-column: span 2;">Error: ${err}</div>`;
                    return;
                }

                globalSilverDinarData = data;
                silverDinarDataLoaded = true;

                // Render perak timestamp
                if (perakTimestamp) {
                    perakTimestamp.textContent = `Terakhir diperbarui: ${data.timestamp || '–'}`;
                }

                // 1. Render Spot Silver Cards
                spotCards.innerHTML = '';
                if (data.silver_spot) {
                    const usdItem = {
                        price: `$${data.silver_spot.usd_per_oz.toFixed(2)}`,
                        change: '',
                        unit: 'oz'
                    };
                    const idrItem = {
                        price: `Rp ${data.silver_spot.idr_per_gram.toLocaleString('id-ID', { maximumFractionDigits: 0 })}`,
                        change: '',
                        unit: 'gr'
                    };
                    
                    spotCards.appendChild(createSpotCard('Spot Perak Dunia (USD)', [usdItem], 'Perak Spot'));
                    spotCards.appendChild(createSpotCard('Spot Perak Dunia (IDR)', [idrItem], 'Perak Spot'));
                } else {
                    spotCards.innerHTML = '<div class="text-center" style="grid-column: span 2; color:var(--text-secondary)">Data spot tidak tersedia</div>';
                }

                // 2. Render Detail Spot Perak Table
                tbodySpot.innerHTML = '';
                if (data.silver_spot_table && data.silver_spot_table.length > 0) {
                    data.silver_spot_table.forEach(row => {
                        const tr = document.createElement('tr');
                        tr.innerHTML = `
                            <td><strong>${row.unit}</strong></td>
                            <td>${row.usd}</td>
                            <td>${row.idr}</td>
                        `;
                        tbodySpot.appendChild(tr);
                    });
                } else {
                    tbodySpot.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-secondary)">Data tidak tersedia</td></tr>';
                }

                // 3. Render Perak Batangan Antam Table
                tbodyAntam.innerHTML = '';
                if (data.silver_antam && data.silver_antam.length > 0) {
                    data.silver_antam.forEach(row => {
                        const tr = document.createElement('tr');
                        const formattedPrice = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(row.price);
                        tr.innerHTML = `
                            <td><strong>${row.gram} gram</strong></td>
                            <td class="text-positive">${formattedPrice}</td>
                        `;
                        tbodyAntam.appendChild(tr);
                    });
                } else {
                    tbodyAntam.innerHTML = '<tr><td colspan="2" class="text-center" style="color:var(--text-secondary)">Data tidak tersedia</td></tr>';
                }

                // 4. Render Dinar KR Table
                tbodyDinar.innerHTML = '';
                if (data.dinar_date) {
                    dinarDateLabel.textContent = `Pembaruan: ${data.dinar_date}`;
                }
                
                if (data.dinar_prices && data.dinar_prices.length > 0) {
                    data.dinar_prices.forEach(row => {
                        const tr = document.createElement('tr');
                        const fmtSell = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(row.sell);
                        const fmtBuy = new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(row.buy);
                        
                        tr.innerHTML = `
                            <td><strong>${row.name}</strong></td>
                            <td class="text-positive">${fmtSell}</td>
                            <td class="text-secondary">${fmtBuy}</td>
                        `;
                        tbodyDinar.appendChild(tr);
                    });
                } else {
                    tbodyDinar.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-secondary)">Data tidak tersedia</td></tr>';
                }

                // 5. Load History Charts for Silver and Dinar
                loadSilverHistoryChart();
                loadDinarHistoryChart();
                loadDinarPrediction(force);
            })
            .catch(err => {
                console.error('Error loading silver/dinar:', err);
                spotCards.innerHTML = `<div class="text-center text-negative" style="grid-column: span 2;">Error: ${err.message}</div>`;
                tbodySpot.innerHTML = '<tr><td colspan="3" class="text-center text-negative">Error</td></tr>';
                tbodyAntam.innerHTML = '<tr><td colspan="2" class="text-center text-negative">Error</td></tr>';
                tbodyDinar.innerHTML = '<tr><td colspan="3" class="text-center text-negative">Error</td></tr>';
                dinarDateLabel.textContent = 'Error';
            });
    }

    function loadSilverHistoryChart() {
        const canvas = document.getElementById('chart-silver-history');
        if (!canvas) return;

        if (state.silverHistoryData) {
            renderSilverChart('all');
            return;
        }

        fetch('/api/silver/history')
            .then(r => r.json())
            .then(data => {
                if (!data || data.length === 0) {
                    console.error('No silver history data returned.');
                    return;
                }
                state.silverHistoryData = data;
                renderSilverChart('all');
            })
            .catch(err => console.error('Failed to load silver history:', err));
    }

    function renderSilverChart(zoomRange) {
        const canvas = document.getElementById('chart-silver-history');
        if (!canvas || !state.silverHistoryData) return;

        let filteredData = state.silverHistoryData;
        if (zoomRange !== 'all') {
            const days = parseInt(zoomRange);
            if (!isNaN(days)) {
                filteredData = state.silverHistoryData.slice(-days);
            }
        }

        const labels = filteredData.map(item => item.date);
        const prices = filteredData.map(item => item.price);

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#94a3b8' : '#475569';
        const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(15,23,42,0.05)';

        if (state.silverChart) {
            state.silverChart.destroy();
        }

        const ctx = canvas.getContext('2d');
        state.silverChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Spot Perak (Rp/gram)',
                    data: prices,
                    borderColor: '#94a3b8',
                    backgroundColor: 'rgba(148, 163, 184, 0.05)',
                    borderWidth: 2,
                    tension: 0.15,
                    pointRadius: filteredData.length > 60 ? 0 : 3,
                    pointHoverRadius: 5,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 2 }).format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            color: textColor,
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 8
                        },
                        grid: {
                            color: gridColor
                        }
                    },
                    y: {
                        ticks: {
                            color: textColor,
                            callback: function(value, index, values) {
                                return 'Rp ' + new Intl.NumberFormat('id-ID', { maximumFractionDigits: 0 }).format(value);
                            }
                        },
                        grid: {
                            color: gridColor
                        }
                    }
                }
            }
        });
    }

    window.zoomSilverChart = function(range) {
        const buttons = {
            7: 'btn-silver-zoom-7d',
            30: 'btn-silver-zoom-30d',
            365: 'btn-silver-zoom-1y',
            'all': 'btn-silver-zoom-all'
        };

        Object.keys(buttons).forEach(key => {
            const btn = document.getElementById(buttons[key]);
            if (btn) {
                if (key.toString() === range.toString()) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            }
        });

        renderSilverChart(range);
    };

    function loadDinarHistoryChart() {
        const canvas = document.getElementById('chart-dinar-history');
        if (!canvas) return;

        if (state.dinarHistoryData) {
            renderDinarChart('all');
            return;
        }

        fetch('/api/dinar/history')
            .then(r => r.json())
            .then(data => {
                if (!data || data.length === 0) {
                    console.error('No dinar history data returned.');
                    return;
                }
                state.dinarHistoryData = data;
                renderDinarChart('all');
            })
            .catch(err => console.error('Failed to load dinar history:', err));
    }

    function renderDinarChart(zoomRange) {
        const canvas = document.getElementById('chart-dinar-history');
        if (!canvas || !state.dinarHistoryData) return;

        let filteredData = state.dinarHistoryData;
        if (zoomRange !== 'all') {
            const days = parseInt(zoomRange);
            if (!isNaN(days)) {
                filteredData = state.dinarHistoryData.slice(-days);
            }
        }

        const labels = filteredData.map(item => item.date);
        const prices = filteredData.map(item => item.price);

        const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        const textColor = isDark ? '#94a3b8' : '#475569';
        const gridColor = isDark ? 'rgba(255,255,255,0.05)' : 'rgba(15,23,42,0.05)';

        if (state.dinarChart) {
            state.dinarChart.destroy();
        }

        const ctx = canvas.getContext('2d');
        state.dinarChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Dinar KR (Rp/koin)',
                    data: prices,
                    borderColor: '#d97706',
                    backgroundColor: 'rgba(217, 119, 6, 0.05)',
                    borderWidth: 2,
                    tension: 0.15,
                    pointRadius: filteredData.length > 60 ? 0 : 3,
                    pointHoverRadius: 5,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                let label = context.dataset.label || '';
                                if (label) {
                                    label += ': ';
                                }
                                if (context.parsed.y !== null) {
                                    label += new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(context.parsed.y);
                                }
                                return label;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        ticks: {
                            color: textColor,
                            maxRotation: 0,
                            autoSkip: true,
                            maxTicksLimit: 6
                        },
                        grid: {
                            color: gridColor
                        }
                    },
                    y: {
                        ticks: {
                            color: textColor,
                            callback: function(value, index, values) {
                                return 'Rp ' + new Intl.NumberFormat('id-ID', { maximumFractionDigits: 0 }).format(value);
                            }
                        },
                        grid: {
                            color: gridColor
                        }
                    }
                }
            }
        });
    }

    window.zoomDinarChart = function(range) {
        const buttons = {
            7: 'btn-dinar-zoom-7d',
            30: 'btn-dinar-zoom-30d',
            365: 'btn-dinar-zoom-1y',
            'all': 'btn-dinar-zoom-all'
        };

        Object.keys(buttons).forEach(key => {
            const btn = document.getElementById(buttons[key]);
            if (btn) {
                if (key.toString() === range.toString()) {
                    btn.classList.add('active');
                } else {
                    btn.classList.remove('active');
                }
            }
        });

        renderDinarChart(range);
    };

    window.switchDinarPredHorizon = function(horizon) {
        state.dinarPredictionHorizon = horizon;
        const btn1d = document.getElementById('btn-dinar-pred-1d');
        const btn1w = document.getElementById('btn-dinar-pred-1w');
        if (btn1d && btn1w) {
            if (horizon === '1d') {
                btn1d.classList.add('active');
                btn1w.classList.remove('active');
            } else {
                btn1w.classList.add('active');
                btn1d.classList.remove('active');
            }
        }
        loadDinarPrediction(false);
    };

    function loadDinarPrediction(force = false) {
        const predContent = document.getElementById('dinar-pred-content');
        const predDate = document.getElementById('dinar-pred-date');
        if (!predContent) return;

        predContent.innerHTML = '<div class="text-center loading" style="padding:1.5rem 0;">Menghitung data model...</div>';
        if (predDate) predDate.textContent = 'Menganalisis...';

        const horizon = state.dinarPredictionHorizon || '1d';
        const url = `/api/dinar/prediction?horizon=${horizon}${force ? '&refresh=1' : ''}`;

        fetch(url)
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    predContent.innerHTML = `<div class="text-center text-negative" style="padding:1rem 0;">Error: ${data.error || 'Gagal memuat prediksi'}</div>`;
                    if (predDate) predDate.textContent = 'Error';
                    return;
                }

                // Update accuracy badge
                const predAccuracy = document.getElementById('dinar-pred-accuracy');
                if (predAccuracy) {
                    if (data.accuracy_pct !== undefined && data.accuracy_pct !== null) {
                        predAccuracy.innerHTML = `🎯 Akurasi: ${data.accuracy_pct.toFixed(2)}%`;
                        predAccuracy.style.display = 'inline-block';
                    } else {
                        predAccuracy.innerHTML = `🎯 Akurasi: Menunggu data`;
                        predAccuracy.style.display = 'inline-block';
                    }
                }

                if (predDate) {
                    const dateToday = new Date(data.date_today);
                    const daysOffset = data.horizon === '1w' ? 7 : 1;
                    dateToday.setDate(dateToday.getDate() + daysOffset);
                    const options = { year: 'numeric', month: 'short', day: 'numeric' };
                    predDate.textContent = `Target: ${dateToday.toLocaleDateString('id-ID', options)}`;
                }

                const fmt = (num) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(num);

                const isSellUp = data.change_sell_pct >= 0;
                const changeSellClass = isSellUp ? 'text-positive' : 'text-negative';
                const changeSellIcon = isSellUp ? '▲' : '▼';
                const changeSellSign = isSellUp ? '+' : '';

                const isBuyUp = data.change_buy_pct >= 0;
                const changeBuyClass = isBuyUp ? 'text-positive' : 'text-negative';
                const changeBuyIcon = isBuyUp ? '▲' : '▼';
                const changeBuySign = isBuyUp ? '+' : '';

                let contentHtml = `
                    <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 8px; padding: 0.75rem; margin-bottom: 1rem;">
                        <div style="font-size:0.75rem; color:var(--text-secondary); text-transform:uppercase; letter-spacing:0.05em; margin-bottom:0.5rem;">
                            Estimasi Proyeksi (10 Dinar)
                        </div>
                        <div style="display:grid; grid-template-columns:1.2fr 1fr; gap:0.5rem; align-items:center; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:0.5rem; margin-bottom:0.5rem;">
                            <div style="font-weight:600; font-size:0.8rem; color:var(--text-secondary);">Harga Beli (Jual Agen)</div>
                            <div style="font-size:0.85rem; font-weight:700; color:var(--text-primary);">${fmt(data.predicted_10d_sell)}</div>
                            <div class="${changeSellClass}" style="font-size:0.7rem; font-weight:500; text-align:right;">
                                ${changeSellIcon} ${changeSellSign}${data.change_sell_pct.toFixed(4)}%
                            </div>
                        </div>
                        <div style="display:grid; grid-template-columns:1.2fr 1fr; gap:0.5rem; align-items:center;">
                            <div style="font-weight:600; font-size:0.8rem; color:var(--text-secondary);">Harga Jual (Buyback)</div>
                            <div style="font-size:0.85rem; font-weight:700; color:var(--text-primary);">${fmt(data.predicted_10d_buy)}</div>
                            <div class="${changeBuyClass}" style="font-size:0.7rem; font-weight:500; text-align:right;">
                                ${changeBuyIcon} ${changeBuySign}${data.change_buy_pct.toFixed(4)}%
                            </div>
                        </div>
                    </div>
                `;

                if (data.horizon === '1w' && data.weekly_trajectory) {
                    let trajRows = '';
                    data.weekly_trajectory.forEach(day => {
                        const dateFormatted = day.date.split('-').reverse().slice(0, 2).join('/');
                        trajRows += `
                            <tr style="border-bottom:1px solid rgba(255,255,255,0.02); font-size:0.75rem;">
                                <td style="padding:0.4rem 0; font-weight:600; color:var(--text-primary);">${day.day_name} <span style="font-size:0.65rem; color:var(--text-secondary); font-weight:normal;">(${dateFormatted})</span></td>
                                <td style="padding:0.4rem 0; font-weight:600; color:#06b6d4;">${fmt(day.predicted_sell)}</td>
                                <td style="padding:0.4rem 0; font-weight:600; color:#f59e0b;">${fmt(day.predicted_buy)}</td>
                            </tr>
                        `;
                    });

                    const bestBuyDateFormatted = data.best_buy_day_info.date.split('-').reverse().slice(0, 2).join('/');
                    const bestSellDateFormatted = data.best_sell_day_info.date.split('-').reverse().slice(0, 2).join('/');

                    contentHtml += `
                        <!-- Best Days Summary Badges -->
                        <div style="background:rgba(255,255,255,0.01); border:1px solid rgba(255,255,255,0.03); border-radius:8px; padding:0.75rem; margin-bottom:1.25rem;">
                            <div style="font-weight:700; font-size:0.75rem; color:var(--text-primary); margin-bottom:0.5rem; display:flex; align-items:center; gap:0.25rem;">
                                📅 Rekomendasi Hari Terbaik (1 Pekan)
                             </div>
                             <div style="display:flex; flex-direction:column; gap:0.5rem;">
                                 <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem;">
                                     <span style="color:var(--text-secondary);">🛒 Hari Beli Terbaik:</span>
                                     <span style="font-weight:700; color:#06b6d4; text-align:right;">
                                         ${data.best_buy_day_info.day_name} (${bestBuyDateFormatted})<br>
                                         <span style="font-size:0.7rem; font-weight:500;">Dinar KR (${fmt(data.best_buy_day_info.price)})</span>
                                     </span>
                                 </div>
                                 <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.75rem; border-top:1px dashed rgba(255,255,255,0.05); padding-top:0.5rem; margin-top:0.25rem;">
                                     <span style="color:var(--text-secondary);">💰 Hari Jual (Buyback) Terbaik:</span>
                                     <span style="font-weight:700; color:#f59e0b; text-align:right;">
                                         ${data.best_sell_day_info.day_name} (${bestSellDateFormatted})<br>
                                         <span style="font-size:0.7rem; font-weight:500;">Dinar KR (${fmt(data.best_sell_day_info.price)})</span>
                                     </span>
                                 </div>
                             </div>
                         </div>

                         <!-- Trajectory Table -->
                         <div class="table-container" style="max-height:180px; overflow-y:auto; border:1px solid rgba(255,255,255,0.03); border-radius:6px; padding:0 0.5rem;">
                             <table style="width:100%; border-collapse:collapse;">
                                 <thead>
                                     <tr style="border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.7rem; text-transform:uppercase; color:var(--text-secondary); text-align:left;">
                                         <th style="padding:0.4rem 0;">Hari</th>
                                         <th style="padding:0.4rem 0;">Beli (Jual Agen)</th>
                                         <th style="padding:0.4rem 0;">Jual (Buyback)</th>
                                     </tr>
                                 </thead>
                                 <tbody>
                                     ${trajRows}
                                 </tbody>
                             </table>
                         </div>
                     `;
                 } else {
                     const driftSign = data.daily_drift >= 0 ? '+' : '';
                     const driftClass = data.daily_drift >= 0 ? 'text-positive' : 'text-negative';
                     contentHtml += `
                         <div style="font-size:0.7rem; color:var(--text-secondary); line-height:1.4;">
                             Laju tren harian Dinar (10 koin) saat ini adalah <strong class="${driftClass}">${driftSign}${fmt(data.daily_drift)}/hari</strong> (berdasarkan regresi linier 10 hari terakhir). Volatilitas per koin 10 hari adalah ${fmt(data.std_dev_10d / 10.0)}.
                         </div>
                     `;
                 }

                 predContent.innerHTML = contentHtml;
             })
             .catch(err => {
                 console.error('Error rendering Dinar prediction:', err);
                 predContent.innerHTML = `<div class="text-center text-negative" style="padding:1rem 0;">Error: ${err.message}</div>`;
             });
     }

    window.switchBankKurs = function(bank) {
        const tbodyKurs = document.getElementById('tbody-kurs');
        if (!globalCommodityData) {
            tbodyKurs.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-secondary)">Data belum dimuat</td></tr>';
            return;
        }

        let list = [];
        if (bank === 'bi') {
            list = globalCommodityData.bi_kurs;
        } else if (bank === 'bca') {
            list = globalCommodityData.bca_kurs;
        } else if (bank === 'mandiri') {
            list = globalCommodityData.mandiri_kurs;
        }

        tbodyKurs.innerHTML = '';
        if (list && list.length > 0) {
            list.forEach(row => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td><strong>${row.kurs}</strong></td>
                    <td>${row.beli}</td>
                    <td>${row.jual}</td>
                `;
                tbodyKurs.appendChild(tr);
            });
        } else {
            tbodyKurs.innerHTML = '<tr><td colspan="3" class="text-center" style="color:var(--text-secondary)">Data kurs tidak tersedia</td></tr>';
        }
    };

    function loadTop5Recommendations(force = false) {
        const top5Grid = document.getElementById('top5-grid');
        const timestampEl = document.getElementById('top5-timestamp');

        // Set loading state
        top5Grid.innerHTML = '<div class="text-center loading" style="padding: 2rem;">Memindai pasar syariah dan merangking emiten...</div>';
        timestampEl.textContent = 'Memperbarui...';

        fetch('/api/top5_recommendations')
            .then(r => r.json())
            .then(data => {
                timestampEl.textContent = 'Terakhir diupdate: ' + new Date().toLocaleTimeString('id-ID');
                globalTop5Data = data;
                top5Loaded = true;

                top5Grid.innerHTML = '';
                if (!data || data.length === 0) {
                    top5Grid.innerHTML = '<div class="text-center" style="padding: 2rem; color:var(--text-secondary);">Tidak ada rekomendasi saham saat ini (seluruh saham tergolong AVOID atau data tidak tersedia).</div>';
                    return;
                }

                data.forEach((item, i) => {
                    const card = document.createElement('div');
                    card.className = 'top5-card';
                    card.setAttribute('data-ticker', item.ticker);

                    const maCrossClass = item.ma_cross === 'GOLDEN' ? 'badge buy' : (item.ma_cross === 'DEATH' ? 'badge sell' : 'badge hold');

                    const narratives = item.narratives || {};
                    const sectorNoteHtml = narratives.sector_note 
                        ? `<div class="narrative-sector-note">📢 <strong>Analisis Sektoral:</strong> ${narratives.sector_note}</div>` 
                        : '';

                    const narrativeHtml = `
                        <div class="narrative-details hidden">
                            ${sectorNoteHtml}
                            <div class="narrative-metrics-grid">
                                <div class="narrative-metric-card">
                                    <div class="narrative-metric-title">📈 EPS Growth (${item.eps_growth || 'N/A'})</div>
                                    <div class="narrative-metric-desc">${narratives.eps_growth || 'Tidak ada analisis.'}</div>
                                </div>
                                <div class="narrative-metric-card">
                                    <div class="narrative-metric-title">💼 ROE (${item.roe || 'N/A'})</div>
                                    <div class="narrative-metric-desc">${narratives.roe || 'Tidak ada analisis.'}</div>
                                </div>
                                <div class="narrative-metric-card">
                                    <div class="narrative-metric-title">🛡️ DER (${item.der || 'N/A'})</div>
                                    <div class="narrative-metric-desc">${narratives.der || 'Tidak ada analisis.'}</div>
                                </div>
                                <div class="narrative-metric-card">
                                    <div class="narrative-metric-title">🏷️ PBV (${item.pbv || 'N/A'})</div>
                                    <div class="narrative-metric-desc">${narratives.pbv || 'Tidak ada analisis.'}</div>
                                </div>
                                <div class="narrative-metric-card">
                                    <div class="narrative-metric-title">⚡ RSI (14) (${item.rsi !== null && item.rsi !== undefined ? item.rsi.toFixed(1) : 'N/A'})</div>
                                    <div class="narrative-metric-desc">${narratives.rsi || 'Tidak ada analisis.'}</div>
                                </div>
                                <div class="narrative-metric-card">
                                    <div class="narrative-metric-title">🔀 MA Cross (${item.ma_cross || 'N/A'})</div>
                                    <div class="narrative-metric-desc">${narratives.ma_cross || 'Tidak ada analisis.'}</div>
                                </div>
                            </div>
                        </div>
                    `;

                    card.innerHTML = `
                        <div class="top5-card-header">
                            <div class="rank-badge-large">${i + 1}</div>
                            <div class="card-main-info">
                                <div class="ticker-name">
                                    ${item.ticker} <span style="font-size:0.95rem; margin-left:0.25rem;">${item.stars}</span>
                                </div>
                                <div class="company-name" title="${item.name}">${item.name}</div>
                                <div class="sector-badge">${item.sector}</div>
                                <div style="font-size:0.75rem; color:var(--text-secondary); margin-top:0.25rem;">
                                    Skor Fund: <strong>${item.fundamental_score}</strong> | Tech: <strong>${item.technical_score}</strong>
                                </div>
                                <button class="btn-narrative-toggle">💡 Penjelasan</button>
                            </div>
                            <div class="metrics-summary">
                                <div class="metric-item">
                                    <span class="metric-label">EPS Growth</span>
                                    <span class="metric-val">${item.eps_growth || 'N/A'}</span>
                                </div>
                                <div class="metric-item">
                                    <span class="metric-label">ROE</span>
                                    <span class="metric-val">${item.roe || 'N/A'}</span>
                                </div>
                                <div class="metric-item">
                                    <span class="metric-label">DER</span>
                                    <span class="metric-val">${item.der || 'N/A'}</span>
                                </div>
                                <div class="metric-item">
                                    <span class="metric-label">PBV</span>
                                    <span class="metric-val">${item.pbv || 'N/A'}</span>
                                </div>
                                <div class="metric-item">
                                    <span class="metric-label">RSI (14)</span>
                                    <span class="metric-val">${item.rsi !== null && item.rsi !== undefined ? item.rsi.toFixed(1) : '–'}</span>
                                </div>
                                <div class="metric-item">
                                    <span class="metric-label">MA Cross</span>
                                    <span class="metric-val">
                                        <span class="tech-badge ${maCrossClass}">${item.ma_cross || '–'}</span>
                                    </span>
                                </div>
                            </div>
                            <div class="card-action-info">
                                <div class="price-large">Rp ${formatRp(item.current_price)}</div>
                                <div><span class="verdict-badge badge ${item.css_class} rec-trigger" style="cursor:pointer;" title="Klik untuk penjelasan">${item.final_signal}</span></div>
                            </div>
                        </div>
                        ${narrativeHtml}
                    `;

                    // Wire up toggle button click
                    const btnToggle = card.querySelector('.btn-narrative-toggle');
                    const narrativeContainer = card.querySelector('.narrative-details');
                    btnToggle.addEventListener('click', (e) => {
                        e.stopPropagation();
                        narrativeContainer.classList.toggle('hidden');
                        btnToggle.innerHTML = narrativeContainer.classList.contains('hidden') 
                            ? '💡 Penjelasan' 
                            : '❌ Tutup Penjelasan';
                    });

                    // Avoid trigger modal click when clicking inside the narrative section
                    narrativeContainer.addEventListener('click', (e) => {
                        e.stopPropagation();
                    });

                    const recTrigger = card.querySelector('.rec-trigger');
                    if (recTrigger) {
                        recTrigger.addEventListener('click', openRecommendationModal);
                    }

                    card.addEventListener('click', () => openModal(item.ticker));
                    top5Grid.appendChild(card);
                });
            })
            .catch(err => {
                timestampEl.textContent = 'Error';
                top5Grid.innerHTML = `<div class="text-center text-negative" style="padding: 2rem;">Gagal memuat rekomendasi: ${err.message}</div>`;
            });
    }

    // ---------- GLOBAL PORTFOLIO (Sirkulasi Investasi) ----------
    let _globalAllocChart = null;
    let _globalGrowthChart = null;
    let _globalData = null;
    let _globalPeriod = 30;

    const CLASS_META = {
        saham_idx: { label: 'Saham IDX', color: '#10b981', icon: '📈' },
        saham_us:  { label: 'Saham US',  color: '#3b82f6', icon: '🌎' },
        emas:      { label: 'Emas',      color: '#f59e0b', icon: '🪙' },
        kas:       { label: 'Kas',       color: '#94a3b8', icon: '💵' },
    };

    function _setText(id, txt) { const el = document.getElementById(id); if (el) el.textContent = txt; }

    function loadGlobalPortfolio() {
        fetch('/api/portfolio/global')
            .then(r => r.json())
            .then(d => { _globalData = d; renderGlobalPortfolio(d); })
            .catch(err => console.error('[global] load failed', err));
    }
    window.loadGlobalPortfolio = loadGlobalPortfolio;

    function renderGlobalPortfolio(d) {
        _setText('global-networth', rupiah(d.net_worth_rp));
        _setText('global-invested', rupiah(d.risk_invested_rp));
        const pnlEl = document.getElementById('global-pnl');
        if (pnlEl) { pnlEl.textContent = rupiah(d.risk_pnl_rp); pnlEl.className = d.risk_pnl_rp >= 0 ? 'text-positive' : 'text-negative'; }
        const gEl = document.getElementById('global-growth-pct');
        if (gEl) { gEl.textContent = pctFmt(d.growth_pct, true); gEl.className = 'global-growth-badge ' + (d.growth_pct >= 0 ? 'positive' : 'negative'); }

        renderAllocChart(d.asset_classes || {});
        renderAllocList(d.asset_classes || {});
        renderCashFlow(d.cash_flow || {});
        renderGrowthChips(d.growth_timeseries || {});
        renderGrowthChart(d.snapshots || [], _globalPeriod);
    }

    function renderAllocChart(classes) {
        const canvas = document.getElementById('global-alloc-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        const keys = Object.keys(CLASS_META).filter(k => (classes[k] && classes[k].value_rp > 0));
        const labels = keys.map(k => CLASS_META[k].label);
        const data = keys.map(k => classes[k].value_rp);
        const colors = keys.map(k => CLASS_META[k].color);
        if (_globalAllocChart) _globalAllocChart.destroy();
        if (keys.length === 0) return;
        _globalAllocChart = new Chart(canvas.getContext('2d'), {
            type: 'doughnut',
            data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] },
            options: {
                responsive: true, maintainAspectRatio: false, cutout: '62%',
                plugins: {
                    legend: { position: 'right', labels: { color: '#cbd5e1', boxWidth: 12, font: { size: 11 } } },
                    tooltip: { callbacks: { label: (ctx) => `${ctx.label}: ${rupiah(ctx.parsed)}` } }
                }
            }
        });
    }

    function renderAllocList(classes) {
        const wrap = document.getElementById('global-alloc-list');
        if (!wrap) return;
        const keys = Object.keys(CLASS_META);
        wrap.innerHTML = keys.map(k => {
            const c = classes[k] || { value_rp: 0, weight_pct: 0, pnl_rp: 0, pnl_pct: 0 };
            const m = CLASS_META[k];
            const isCash = (k === 'kas');
            const pnlClass = c.pnl_rp >= 0 ? 'text-positive' : 'text-negative';
            const growthHtml = isCash ? '<span class="muted">—</span>'
                : `<span class="${pnlClass}">${pctFmt(c.pnl_pct, true)}</span>`;
            return `
                <div class="global-alloc-card" style="border-left:4px solid ${m.color};">
                    <div class="gac-top">
                        <span class="gac-label">${m.icon} ${m.label}</span>
                        <span class="gac-weight">${(c.weight_pct || 0).toFixed(1)}%</span>
                    </div>
                    <div class="gac-value">${rupiah(c.value_rp)}</div>
                    <div class="gac-bar"><span style="width:${Math.min(100, c.weight_pct || 0)}%; background:${m.color};"></span></div>
                    <div class="gac-foot">
                        <span class="muted">Pertumbuhan</span> ${growthHtml}
                    </div>
                </div>`;
        }).join('');
    }

    function renderCashFlow(cf) {
        const wrap = document.getElementById('global-cashflow');
        if (!wrap) return;
        const cards = [
            { label: 'Modal Masuk (TopUp)', val: cf.deposit_rp, cls: 'text-positive', icon: '📥' },
            { label: 'Modal Keluar (Tarik)', val: cf.withdrawal_rp, cls: 'text-negative', icon: '📤' },
            { label: 'Net Modal Disetor', val: cf.net_modal_rp, cls: 'text-neutral', icon: '🏦' },
            { label: 'Total Pembelian', val: cf.buy_rp, cls: 'text-neutral', icon: '🛒' },
            { label: 'Total Penjualan', val: cf.sell_rp, cls: 'text-neutral', icon: '💱' },
            { label: 'Realized P/L', val: cf.realized_pnl_rp, cls: (cf.realized_pnl_rp >= 0 ? 'text-positive' : 'text-negative'), icon: '✅' },
        ];
        wrap.innerHTML = cards.map(c => `
            <div class="global-cf-card">
                <span class="gcf-icon">${c.icon}</span>
                <div class="gcf-info">
                    <span class="gcf-label">${c.label}</span>
                    <span class="gcf-value ${c.cls}">${rupiah(c.val)}</span>
                </div>
            </div>`).join('');
    }

    function renderGrowthChips(g) {
        const wrap = document.getElementById('global-growth-chips');
        if (!wrap) return;
        const chip = (label, v) => {
            const cls = (v > 0) ? 'positive' : (v < 0 ? 'negative' : 'neutral');
            return `<span class="growth-chip ${cls}">${label}: ${pctFmt(v, true)}</span>`;
        };
        wrap.innerHTML = chip('Harian', g.daily || 0) + chip('Mingguan', g.weekly || 0)
            + chip('Bulanan', g.monthly || 0) + chip('Total', g.all || 0);
        const note = document.getElementById('global-growth-note');
        if (note) {
            note.textContent = g.n_points
                ? `Berdasarkan ${g.n_points} snapshot harian sejak ${g.since_date}. Snapshot terekam otomatis tiap kali tab dibuka.`
                : 'Snapshot pertumbuhan akan terkumpul seiring waktu (1 titik/hari).';
        }
    }

    function renderGrowthChart(snapshots, periodDays) {
        const canvas = document.getElementById('global-growth-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        let snaps = (snapshots || []).slice();
        if (periodDays && periodDays > 0 && snaps.length > periodDays) {
            snaps = snaps.slice(-periodDays);
        }
        const labels = snaps.map(s => String(s.date).slice(5)); // MM-DD
        const data = snaps.map(s => Number(s.net_worth_rp) || 0);
        if (_globalGrowthChart) _globalGrowthChart.destroy();
        const ctx = canvas.getContext('2d');
        const grad = ctx.createLinearGradient(0, 0, 0, 220);
        grad.addColorStop(0, 'rgba(59,130,246,0.35)');
        grad.addColorStop(1, 'rgba(59,130,246,0.02)');
        _globalGrowthChart = new Chart(ctx, {
            type: 'line',
            data: { labels, datasets: [{
                label: 'Net Worth', data, borderColor: '#3b82f6', backgroundColor: grad,
                fill: true, tension: 0.3, pointRadius: snaps.length > 60 ? 0 : 2,
                pointHoverRadius: 4, borderWidth: 2,
            }]},
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: { callbacks: { label: (c) => rupiah(c.parsed.y) } }
                },
                scales: {
                    x: { ticks: { color: '#64748b', maxTicksLimit: 8, font: { size: 10 } }, grid: { display: false } },
                    y: { ticks: { color: '#64748b', font: { size: 10 }, callback: (v) => rupiah(v) }, grid: { color: 'rgba(148,163,184,0.08)' } }
                }
            }
        });
    }

    // Period toggle
    const _gpToggle = document.getElementById('global-period-toggle');
    if (_gpToggle) {
        _gpToggle.addEventListener('click', (e) => {
            const btn = e.target.closest('.gp-btn');
            if (!btn) return;
            _gpToggle.querySelectorAll('.gp-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            _globalPeriod = parseInt(btn.dataset.period) || 0;
            if (_globalData) renderGrowthChart(_globalData.snapshots || [], _globalPeriod);
        });
    }
    const _btnRefreshGlobal = document.getElementById('btn-refresh-global');
    if (_btnRefreshGlobal) _btnRefreshGlobal.addEventListener('click', loadGlobalPortfolio);

    // ---------- PORTFOLIO TAB LOGIC ----------
    function loadBrokerPortfolio() {
        fetch('/api/broker_portfolio')
            .then(r => r.json())
            .then(data => {
                // 1. Overview stats
                const sum = data.summary;
                document.getElementById('port-total-value').textContent = `Rp ${formatRp(sum.total_value)}`;
                document.getElementById('port-total-invested').textContent = `Rp ${formatRp(sum.total_invested)}`;
                
                // Unrealized P/L
                const uPnlEl = document.getElementById('port-unrealized-pnl');
                uPnlEl.textContent = `Rp ${formatRp(sum.unrealized_pnl_rp)}`;
                uPnlEl.className = sum.unrealized_pnl_rp >= 0 ? 'text-positive font-bold' : 'text-negative font-bold';
                
                // Realized P/L
                const rPnlEl = document.getElementById('port-realized-pnl');
                rPnlEl.textContent = `Rp ${formatRp(sum.realized_pnl_rp)}`;
                rPnlEl.className = sum.realized_pnl_rp >= 0 ? 'text-positive font-bold' : 'text-negative font-bold';

                // Total P/L % badge
                const pctEl = document.getElementById('port-total-pnl-pct');
                const sign = sum.total_pnl_rp >= 0 ? '+' : '';
                pctEl.textContent = `${sign}${sum.total_pnl_pct.toFixed(2)}%`;
                pctEl.className = `stat-badge ${sum.total_pnl_rp >= 0 ? 'positive' : 'negative'}`;

                // 2a. Tampilkan warnings sync (kalau ada konflik portfolio.csv vs broker_transactions)
                const warningsBox = document.getElementById('port-sync-warnings');
                const warningsList = sum.warnings || [];
                if (warningsBox) {
                    if (warningsList.length === 0) {
                        warningsBox.innerHTML = '';
                        warningsBox.style.display = 'none';
                    } else {
                        warningsBox.style.display = 'block';
                        warningsBox.innerHTML = `
                            <strong>⚠ Sinkronisasi data:</strong>
                            <ul style="margin: 0.5rem 0 0 1rem; padding: 0; font-size: 0.82rem;">
                                ${warningsList.map(w => `<li>${w}</li>`).join('')}
                            </ul>
                        `;
                    }
                }

                // 2b. Platforms
                // Pegadaian update terpisah (sudah handle di loadPegadaianPortfolio)
                for (const [plat, pData] of Object.entries(sum.platforms)) {
                    let prefix = '';
                    if (plat === 'Bibit') prefix = 'bibit';
                    else if (plat === 'Pluang') prefix = 'pluang';
                    else if (plat === 'Profit Anywhere') prefix = 'profit';
                    // Pegadaian sudah di-render oleh loadPegadaianPortfolio

                    if (prefix) {
                        document.getElementById(`${prefix}-cash`).textContent = `Rp ${formatRp(pData.cash)}`;
                        document.getElementById(`${prefix}-stock-val`).textContent = `Rp ${formatRp(pData.stock_value)}`;
                        document.getElementById(`${prefix}-total-val`).textContent = `Rp ${formatRp(pData.total_value)}`;
                        document.getElementById(`${prefix}-invested`).textContent = `Rp ${formatRp(pData.total_invested)}`;
                        
                        const pnlRpEl = document.getElementById(`${prefix}-pnl-rp`);
                        pnlRpEl.textContent = `Rp ${formatRp(pData.pnl_rp)}`;
                        pnlRpEl.className = pData.pnl_rp >= 0 ? 'text-positive' : 'text-negative';

                        const pnlPctEl = document.getElementById(`${prefix}-pnl-pct`);
                        const pSign = pData.pnl_rp >= 0 ? '+' : '';
                        pnlPctEl.textContent = `${pSign}${pData.pnl_pct.toFixed(2)}%`;
                        pnlPctEl.className = `plat-badge ${pData.pnl_rp >= 0 ? 'positive' : 'negative'}`;
                    }
                }

                // 3. Active Holdings Table
                const tbodyHoldings = document.getElementById('tbody-holdings');
                tbodyHoldings.innerHTML = '';
                if (!data.holdings || data.holdings.length === 0) {
                    tbodyHoldings.innerHTML = `<tr><td colspan="7" class="text-center" style="color:var(--text-secondary); padding: 2rem;">Belum ada kepemilikan saham aktif. Silakan tambahkan transaksi beli (BUY).</td></tr>`;
                } else {
                    data.holdings.forEach(h => {
                        const tr = document.createElement('tr');
                        
                        // Format amount (Lot vs Lembar)
                        let qtyStr = '';
                        if (h.platform === 'Pluang') {
                            qtyStr = `${h.shares.toLocaleString('id-ID')} Lembar`;
                        } else {
                            qtyStr = `${h.lot.toLocaleString('id-ID')} Lot (${h.shares.toLocaleString('id-ID')} Lbr)`;
                        }

                        const pSign = h.pnl_rp >= 0 ? '+' : '';
                        const pClass = h.pnl_rp >= 0 ? 'text-positive font-bold' : 'text-negative font-bold';

                        tr.innerHTML = `
                            <td><strong>${h.ticker}</strong><br><small style="color:var(--text-secondary)">${h.name}</small></td>
                            <td><span class="badge ${h.platform === 'Bibit' ? 'buy' : (h.platform === 'Pluang' ? 'hold' : 'sell')}" style="padding: 0.15rem 0.4rem; font-size: 0.75rem;">${h.platform}</span></td>
                            <td style="text-align:right;">Rp ${formatRp(h.avg_price)}</td>
                            <td style="text-align:right;">${qtyStr}</td>
                            <td style="text-align:right;">Rp ${formatRp(h.current_price)}</td>
                            <td style="text-align:right; font-weight:600;">Rp ${formatRp(h.current_value)}</td>
                            <td style="text-align:right;" class="${pClass}">Rp ${formatRp(h.pnl_rp)}<br><small>${pSign}${h.pnl_pct.toFixed(2)}%</small></td>
                        `;
                        tbodyHoldings.appendChild(tr);
                    });
                }

                // 4. Transactions Ledger History
                const tbodyTransactions = document.getElementById('tbody-transactions');
                tbodyTransactions.innerHTML = '';
                if (!data.transactions || data.transactions.length === 0) {
                    tbodyTransactions.innerHTML = `<tr><td colspan="9" class="text-center" style="color:var(--text-secondary); padding: 2rem;">Belum ada riwayat transaksi.</td></tr>`;
                } else {
                    data.transactions.forEach(tx => {
                        const tr = document.createElement('tr');
                        
                        // Format Tipe Badge
                        let tClass = 'badge ';
                        if (tx.tipe === 'BUY') tClass += 'buy';
                        else if (tx.tipe === 'SELL') tClass += 'sell';
                        else if (tx.tipe === 'WITHDRAWAL') tClass += 'withdrawal';
                        else tClass += 'hold';
                        
                        // Format Jumlah Lot / Lembar
                        let qtyStr = '–';
                        if (tx.tipe !== 'TOPUP' && tx.tipe !== 'WITHDRAWAL') {
                            if (tx.platform === 'Pluang') {
                                qtyStr = `${tx.jumlah.toLocaleString('id-ID')} Lbr`;
                            } else {
                                qtyStr = `${(tx.jumlah / 100).toLocaleString('id-ID')} Lot`;
                            }
                        }

                        // Ticker/Harga
                        const tickerStr = tx.ticker || '–';
                        const hargaStr = tx.harga > 0 ? `Rp ${formatRp(tx.harga)}` : '–';
                        const nominalStr = `Rp ${formatRp(tx.nominal)}`;
                        
                        // Realized P/L display
                        let pnlStr = '–';
                        if (tx.tipe === 'SELL') {
                            const sign = tx.pnl_rp >= 0 ? '+' : '';
                            const pClass = tx.pnl_rp >= 0 ? 'text-positive' : 'text-negative';
                            pnlStr = `<span class="${pClass}">${sign}Rp ${formatRp(tx.pnl_rp)} (${sign}${tx.pnl_pct.toFixed(1)}%)</span>`;
                        }

                        tr.innerHTML = `
                            <td><small>${tx.tanggal}</small></td>
                            <td><small>${tx.platform}</small></td>
                            <td><span class="${tClass}" style="padding: 0.15rem 0.4rem; font-size: 0.7rem;">${tx.tipe}</span></td>
                            <td><strong>${tickerStr}</strong></td>
                            <td style="text-align:right;">${hargaStr}</td>
                            <td style="text-align:right;"><small>${qtyStr}</small></td>
                            <td style="text-align:right;">${nominalStr}</td>
                            <td style="text-align:right;">${pnlStr}</td>
                            <td style="text-align:center;">
                                <button class="btn icon-btn text-negative delete-tx-btn" data-id="${tx.id}" style="padding: 0.2rem; font-size: 0.85rem;" title="Hapus">🗑️</button>
                           </td>
                        `;
                        tbodyTransactions.appendChild(tr);
                    });

                    // Attach event listeners to delete buttons
                    tbodyTransactions.querySelectorAll('.delete-tx-btn').forEach(btn => {
                        btn.addEventListener('click', (e) => {
                            e.stopPropagation();
                            const txId = btn.getAttribute('data-id');
                            if (confirm('Apakah Anda yakin ingin menghapus transaksi ini?')) {
                                deleteTransaction(txId);
                            }
                        });
                    });
                }
            })
            .catch(err => {
                console.error('Error loading portfolio:', err);
            });
    }

    function deleteTransaction(txId) {
        fetch(`/api/broker_portfolio/transaction/${txId}`, { method: 'DELETE' })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    loadBrokerPortfolio();
                    if (window.loadGlobalPortfolio) window.loadGlobalPortfolio();
                } else {
                    alert('Gagal menghapus transaksi: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
    }

    // Set default date to today
    function setDefaultTxDate() {
        const today = new Date();
        const yyyy = today.getFullYear();
        const mm = String(today.getMonth() + 1).padStart(2, '0');
        const dd = String(today.getDate()).padStart(2, '0');
        const dateInput = document.getElementById('tx-date');
        if (dateInput) {
            dateInput.value = `${yyyy}-${mm}-${dd}`;
        }
    }
    setDefaultTxDate();

    // Form inputs and validation setup
    const txPlatform = document.getElementById('tx-platform');
    const txType = document.getElementById('tx-type');
    const txTicker = document.getElementById('tx-ticker');
    const txPrice = document.getElementById('tx-price');
    const txAmount = document.getElementById('tx-amount');
    const txBrokerFee = document.getElementById('tx-broker-fee');
    const txExchangeFee = document.getElementById('tx-exchange-fee');
    const txNominal = document.getElementById('tx-nominal');
    const txTickerLabel = document.getElementById('tx-ticker-label');
    const txAmountLabel = document.getElementById('tx-amount-label');

    if (txPlatform && txType) {
        function updateFormFieldsStatus() {
            const plat = txPlatform.value;
            const type = txType.value;

            // 1. Label quantity
            if (plat === 'Pluang') {
                if (txAmountLabel) txAmountLabel.textContent = 'Jumlah (Lembar)';
                if (txAmount) txAmount.placeholder = 'misal: 2.5';
            } else {
                if (txAmountLabel) txAmountLabel.textContent = 'Jumlah (Lot)';
                if (txAmount) txAmount.placeholder = 'misal: 5';
            }

            // 2. Disabling logic
            if (type === 'TOPUP' || type === 'WITHDRAWAL') {
                if (txTicker) { txTicker.disabled = true; txTicker.required = false; txTicker.value = ''; }
                if (txPrice) { txPrice.disabled = true; txPrice.required = false; txPrice.value = ''; }
                if (txAmount) { txAmount.disabled = true; txAmount.required = false; txAmount.value = ''; }
                if (txBrokerFee) { txBrokerFee.disabled = true; txBrokerFee.required = false; txBrokerFee.value = '0'; }
                if (txExchangeFee) { txExchangeFee.disabled = true; txExchangeFee.required = false; txExchangeFee.value = '0'; }
                if (txNominal) { txNominal.disabled = false; txNominal.required = true; }
            } else {
                if (txTicker) { txTicker.disabled = false; txTicker.required = true; }
                if (txPrice) { txPrice.disabled = false; txPrice.required = true; }
                if (txAmount) { txAmount.disabled = false; txAmount.required = true; }
                if (txBrokerFee) { txBrokerFee.disabled = false; txBrokerFee.required = false; if (!txBrokerFee.value) txBrokerFee.value = '0'; }
                if (txExchangeFee) { txExchangeFee.disabled = false; txExchangeFee.required = false; if (!txExchangeFee.value) txExchangeFee.value = '0'; }
                if (txNominal) { txNominal.disabled = true; txNominal.required = false; }
                recalcNominal();
            }
        }

        function recalcNominal() {
            const type = txType.value;
            if (type === 'TOPUP' || type === 'WITHDRAWAL') return;

            const plat = txPlatform.value;
            const price = parseFloat(txPrice.value) || 0;
            const amount = parseFloat(txAmount.value) || 0;
            const brokerFee = parseFloat(txBrokerFee.value) || 0;
            const exchangeFee = parseFloat(txExchangeFee.value) || 0;

            const multiplier = (plat === 'Bibit' || plat === 'Profit Anywhere') ? 100 : 1;
            let nominal = price * amount * multiplier;
            
            if (type === 'BUY') {
                nominal += brokerFee + exchangeFee;
            } else if (type === 'SELL') {
                nominal -= (brokerFee + exchangeFee);
            }

            if (txNominal) {
                txNominal.value = nominal > 0 ? Math.round(nominal) : '';
            }
        }

        txPlatform.addEventListener('change', updateFormFieldsStatus);
        txType.addEventListener('change', updateFormFieldsStatus);
        if (txPrice) txPrice.addEventListener('input', recalcNominal);
        if (txAmount) txAmount.addEventListener('input', recalcNominal);
        if (txBrokerFee) txBrokerFee.addEventListener('input', recalcNominal);
        if (txExchangeFee) txExchangeFee.addEventListener('input', recalcNominal);

        // Initialize state
        updateFormFieldsStatus();
    }

    // Submit handler
    const formTx = document.getElementById('form-broker-transaction');
    if (formTx) {
        formTx.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const type = txType.value;
            const plat = txPlatform.value;
            const ticker = txTicker.value.trim().toUpperCase();
            const price = parseFloat(txPrice.value) || 0;
            const amount = parseFloat(txAmount.value) || 0;
            const brokerFee = parseFloat(txBrokerFee.value) || 0;
            const exchangeFee = parseFloat(txExchangeFee.value) || 0;
            const nominal = parseFloat(txNominal.value) || 0;
            const date = document.getElementById('tx-date').value;

            // Convert amount in Lots to Shares for Bibit/Profit Anywhere if BUY/SELL
            let shares = amount;
            if (type !== 'TOPUP' && type !== 'WITHDRAWAL') {
                if (plat === 'Bibit' || plat === 'Profit Anywhere') {
                    shares = amount * 100;
                }
            }

            const payload = {
                tanggal: date,
                platform: plat,
                tipe: type,
                ticker: (type === 'TOPUP' || type === 'WITHDRAWAL') ? '' : ticker,
                harga: (type === 'TOPUP' || type === 'WITHDRAWAL') ? 0 : price,
                jumlah: (type === 'TOPUP' || type === 'WITHDRAWAL') ? 0 : shares,
                nominal: nominal,
                broker_fee: (type === 'TOPUP' || type === 'WITHDRAWAL') ? 0 : brokerFee,
                exchange_fee: (type === 'TOPUP' || type === 'WITHDRAWAL') ? 0 : exchangeFee
            };

            fetch('/api/broker_portfolio/transaction', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    formTx.reset();
                    setDefaultTxDate();
                    clearReviewMode();
                    updateFormFieldsStatus();
                    loadBrokerPortfolio();
                    if (window.loadGlobalPortfolio) window.loadGlobalPortfolio();
                } else {
                    alert('Gagal menyimpan transaksi: ' + (data.error || 'Error tidak dikenal'));
                }
            })
            .catch(err => alert('Error: ' + err.message));
        });
    }

    // AI Scanner upload handlers
    const dropzone = document.getElementById('screenshot-dropzone');
    const fileInput = document.getElementById('screenshot-file-input');
    const formPanel = document.querySelector('.form-entry-panel');
    const reviewBanner = document.getElementById('form-review-banner');
    const btnClearReview = document.getElementById('btn-clear-form-review');

    if (dropzone && fileInput) {
        const scannerLine = dropzone.querySelector('.scanner-line');

        // Drag events
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('dragover');
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                handleScreenshotFile(files[0]);
            }
        });

        // Click event
        dropzone.addEventListener('click', () => {
            fileInput.click();
        });

        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                handleScreenshotFile(fileInput.files[0]);
            }
        });

        function handleScreenshotFile(file) {
            if (!file.type.startsWith('image/')) {
                alert('Hanya berkas gambar (.png, .jpg, .webp) yang diperbolehkan!');
                return;
            }

            // Show scan animation
            if (scannerLine) scannerLine.classList.remove('hidden');

            const formData = new FormData();
            formData.append('file', file);

            fetch('/api/broker_portfolio/upload_screenshot', {
                method: 'POST',
                body: formData
            })
            .then(r => r.json())
            .then(res => {
                if (scannerLine) scannerLine.classList.add('hidden');
                if (res.success && res.data) {
                    enterReviewMode(res.data);
                } else {
                    alert('Gagal mendeteksi bukti transaksi: ' + (res.error || 'Format tidak didukung'));
                }
            })
            .catch(err => {
                if (scannerLine) scannerLine.classList.add('hidden');
                alert('Gagal mengunggah gambar: ' + err.message);
            });
        }

        function enterReviewMode(data) {
            if (txPlatform) txPlatform.value = data.platform || 'Bibit';
            if (txType) txType.value = data.tipe || 'BUY';
            if (txTicker) txTicker.value = data.ticker || '';
            if (txPrice) txPrice.value = data.harga || '';
            
            // Convert shares from API to Lots for Bibit/Profit Anywhere
            if (data.tipe !== 'TOPUP' && data.tipe !== 'WITHDRAWAL' && txAmount) {
                if (data.platform === 'Bibit' || data.platform === 'Profit Anywhere') {
                    txAmount.value = (data.jumlah / 100) || '';
                } else {
                    txAmount.value = data.jumlah || '';
                }
            } else if (txAmount) {
                txAmount.value = '';
            }
            
            if (txBrokerFee) txBrokerFee.value = data.broker_fee || 0;
            if (txExchangeFee) txExchangeFee.value = data.exchange_fee || 0;
            
            if (txNominal) txNominal.value = data.nominal || '';

            setDefaultTxDate();
            updateFormFieldsStatus();

            // Highlight form
            if (formPanel) formPanel.classList.add('review-mode');
            if (reviewBanner) reviewBanner.classList.remove('hidden');
            if (btnClearReview) btnClearReview.classList.remove('hidden');
            
            const titleEl = document.getElementById('form-entry-title');
            if (titleEl) titleEl.textContent = '🔍 Review Hasil Scan';

            // Highlight input fields temporarily
            const fields = [txPlatform, txType, txTicker, txPrice, txAmount, txNominal].filter(Boolean);
            fields.forEach(f => {
                if (f.value !== '' && f.value !== 0) {
                    f.classList.add('highlight-field');
                }
            });

            setTimeout(() => {
                fields.forEach(f => f.classList.remove('highlight-field'));
            }, 3000);
        }

        function clearReviewMode() {
            if (formPanel) formPanel.classList.remove('review-mode');
            if (reviewBanner) reviewBanner.classList.add('hidden');
            if (btnClearReview) btnClearReview.classList.add('hidden');
            
            const titleEl = document.getElementById('form-entry-title');
            if (titleEl) titleEl.textContent = '📝 Tambah Transaksi Manual';
            fileInput.value = '';
        }

        if (btnClearReview) {
            btnClearReview.addEventListener('click', (e) => {
                e.preventDefault();
                if (formTx) formTx.reset();
                setDefaultTxDate();
                clearReviewMode();
                updateFormFieldsStatus();
            });
        }
    }

    // ==========================================
    // ======= TRADER SAKTI HUB LOGIC ===========
    // ==========================================

    function parseRpText(text) {
        if (!text) return 0;
        let clean = text.replace(/Rp\s?/g, '').trim();
        if (clean.includes(',')) {
            clean = clean.replace(/\./g, '').replace(/,/g, '.');
        } else {
            clean = clean.replace(/\./g, '');
        }
        return parseFloat(clean) || 0;
    }

    window.switchTSSubTab = function(subtab) {
        const subtabs = ['mantra', 'compounding', 'risk', 'checklist', 'predictor'];
        subtabs.forEach(t => {
            const btn = document.getElementById(`ts-subtab-btn-${t}`);
            const content = document.getElementById(`ts-subtab-${t}-content`);
            if (t === subtab) {
                if (btn) btn.classList.add('active');
                if (content) content.classList.remove('hidden');
            } else {
                if (btn) btn.classList.remove('active');
                if (content) content.classList.add('hidden');
            }
        });
        
        // Trigger tab-specific refresh
        if (subtab === 'compounding') {
            recalculateCompounding();
        } else if (subtab === 'risk') {
            recalculateRiskAndMM();
        } else if (subtab === 'checklist') {
            renderChecklist();
        } else if (subtab === 'predictor') {
            initShariaPredictor();
        }
    };

    // --- Mantra Hub ---
    function renderMantras(filterText = '', filterTrigger = '') {
        const grid = document.getElementById('mantra-grid');
        if (!grid) return;
        grid.innerHTML = '';
        
        const filtered = tradersakti_mantras.filter(m => {
            const matchText = m.mantra.toLowerCase().includes(filterText.toLowerCase()) || 
                              m.explanation.toLowerCase().includes(filterText.toLowerCase());
            const matchTrigger = filterTrigger === '' || m.trigger === filterTrigger;
            return matchText && matchTrigger;
        });
        
        filtered.forEach(m => {
            const card = document.createElement('div');
            card.className = 'mantra-grid-card';
            card.innerHTML = `
                <div class="mantra-grid-header">
                    <span>Mantra #${m.no}</span>
                    <span style="font-size: 0.75rem; color: #60a5fa;">${m.trigger}</span>
                </div>
                <div class="mantra-grid-text">${m.mantra}</div>
                <div class="mantra-grid-explanation">${m.explanation}</div>
            `;
            grid.appendChild(card);
        });
    }

    // --- Compounding Engine ---
    function recalculateCompounding() {
        const modalAwal = parseFloat(document.getElementById('comp-input-modal').value) || 50000000;
        const target = parseFloat(document.getElementById('comp-input-target').value) || 2000000000;
        const steps = parseInt(document.getElementById('comp-input-steps').value) || 18;
        const defaultTrades = parseInt(document.getElementById('comp-input-trades').value) || 4;
        const preset = document.getElementById('comp-select-preset').value;

        let customGrowth = {};
        try {
            customGrowth = JSON.parse(localStorage.getItem('tradersakti_comp_custom_growth') || '{}');
        } catch(e){}
        let customTrades = {};
        try {
            customTrades = JSON.parse(localStorage.getItem('tradersakti_comp_custom_trades') || '{}');
        } catch(e){}
        let customNotes = {};
        try {
            customNotes = JSON.parse(localStorage.getItem('tradersakti_comp_custom_notes') || '{}');
        } catch(e){}
        let checkedSteps = [];
        try {
            checkedSteps = JSON.parse(localStorage.getItem('tradersakti_comp_checked_steps') || '[]');
        } catch(e){}

        const isCustomPreset = (preset === 'custom');

        let growthRates = [];
        if (preset === 'equalized') {
            const eqGrowth = Math.pow(target / modalAwal, 1 / steps) - 1;
            for (let i = 0; i < steps; i++) {
                growthRates.push(eqGrowth);
            }
        } else {
            let presetKey = "";
            if (preset === 'conservative') presetKey = "Konservatif → naik bertahap";
            else if (preset === 'moderate') presetKey = "Moderate → 8–12%";
            else if (preset === 'aggressive') presetKey = "Agresif (berisiko tinggi)";

            const presetArr = tradersakti_presets[presetKey] || [];
            for (let i = 0; i < steps; i++) {
                if (preset === 'custom') {
                    const saved = customGrowth[i + 1];
                    if (saved !== undefined) {
                        growthRates.push(parseFloat(saved) / 100);
                    } else {
                        const eqGrowth = Math.pow(target / modalAwal, 1 / steps) - 1;
                        growthRates.push(eqGrowth);
                    }
                } else {
                    if (i < presetArr.length) {
                        growthRates.push(presetArr[i]);
                    } else {
                        growthRates.push(presetArr[presetArr.length - 1] || 0.1);
                    }
                }
            }
        }

        const tbody = document.getElementById('comp-tbody');
        if (!tbody) return;
        tbody.innerHTML = '';

        let currentBalance = modalAwal;
        let sumGrowth = 0;
        let sumTradeGrowth = 0;

        for (let i = 1; i <= steps; i++) {
            const stepGrowth = growthRates[i - 1];
            const stepAwal = currentBalance;
            const stepAkhir = stepAwal * (1 + stepGrowth);
            currentBalance = stepAkhir;

            let stepTrades = defaultTrades;
            if (preset === 'custom') {
                const savedT = customTrades[i];
                if (savedT !== undefined) stepTrades = parseInt(savedT);
            }
            const tradeGrowth = Math.pow(1 + stepGrowth, 1 / stepTrades) - 1;

            sumGrowth += stepGrowth;
            sumTradeGrowth += tradeGrowth;

            const isChecked = checkedSteps.includes(i);
            const noteVal = customNotes[i] || '';

            const row = document.createElement('tr');
            if (isChecked) row.className = 'comp-checked-row';
            row.style.borderBottom = '1px solid var(--panel-border)';

            row.innerHTML = `
                <td style="padding: 0.6rem 0.5rem; text-align: center;">
                    <input type="checkbox" class="comp-step-check" data-step="${i}" ${isChecked ? 'checked' : ''}>
                </td>
                <td style="padding: 0.6rem 0.5rem;">
                    <input type="number" class="comp-step-growth" data-step="${i}" value="${(stepGrowth * 100).toFixed(2)}" step="0.1" style="width: 75px; background: rgba(0,0,0,0.2); border: 1px solid var(--panel-border); color: var(--text-primary); border-radius: 4px; padding: 0.2rem;" ${!isCustomPreset ? 'disabled' : ''}> %
                </td>
                <td style="padding: 0.6rem 0.5rem; text-align: right; color: var(--text-secondary);">
                    Rp ${formatRp(stepAwal)}
                </td>
                <td style="padding: 0.6rem 0.5rem; text-align: right; font-weight: bold; color: var(--text-primary);">
                    Rp ${formatRp(stepAkhir)}
                </td>
                <td style="padding: 0.6rem 0.5rem; text-align: center;">
                    <input type="number" class="comp-step-trades" data-step="${i}" value="${stepTrades}" min="1" max="100" style="width: 50px; background: rgba(0,0,0,0.2); border: 1px solid var(--panel-border); color: var(--text-primary); border-radius: 4px; padding: 0.2rem; text-align: center;" ${!isCustomPreset ? 'disabled' : ''}>
                </td>
                <td style="padding: 0.6rem 0.5rem; text-align: right; color: #60a5fa;">
                    ${(tradeGrowth * 100).toFixed(2)}% / trade
                </td>
                <td style="padding: 0.6rem 0.5rem; text-align: center;">
                    <span class="comp-status-indicator ${isChecked ? 'comp-status-done' : 'comp-status-pending'}">
                        ${isChecked ? 'SELESAI' : 'PENDING'}
                    </span>
                </td>
                <td style="padding: 0.6rem 0.5rem;">
                    <input type="text" class="comp-step-note" data-step="${i}" value="${noteVal}" placeholder="Rencana emiten & setup..." style="width: 100%; background: rgba(0,0,0,0.2); border: 1px solid var(--panel-border); color: var(--text-primary); border-radius: 4px; padding: 0.2rem 0.4rem;">
                </td>
            `;

            tbody.appendChild(row);
        }

        const avgGrowth = sumGrowth / steps;
        const avgTradeGrowth = sumTradeGrowth / steps;
        const endingBalance = currentBalance;
        const gap = target - endingBalance;

        document.getElementById('comp-kpi-avg-growth').textContent = (avgGrowth * 100).toFixed(2) + '%';
        document.getElementById('comp-kpi-avg-trade-growth').textContent = `Growth/Trade: ${(avgTradeGrowth * 100).toFixed(2)}%`;
        document.getElementById('comp-kpi-ending-balance').textContent = `Rp ${formatRp(endingBalance)}`;
        
        const gapEl = document.getElementById('comp-kpi-gap');
        if (gap <= 0) {
            gapEl.textContent = 'Rp 0 (Target Terlampaui)';
            gapEl.style.color = 'var(--color-buy)';
        } else {
            gapEl.textContent = `Rp ${formatRp(gap)}`;
            gapEl.style.color = 'var(--text-primary)';
        }

        const statusEl = document.getElementById('comp-kpi-status');
        if (endingBalance >= target) {
            statusEl.textContent = 'TERCAPAI 🚀';
            statusEl.style.color = 'var(--color-buy)';
        } else {
            statusEl.textContent = 'BELUM TERCAPAI ⏳';
            statusEl.style.color = '#ef4444';
        }

        let progressPct = 0;
        if (endingBalance > modalAwal) {
            progressPct = Math.min(100, Math.max(0, (Math.log(endingBalance / modalAwal) / Math.log(target / modalAwal)) * 100));
        }
        document.getElementById('comp-progress-pct').textContent = progressPct.toFixed(1) + '%';
        document.getElementById('comp-progress-bar').style.width = progressPct + '%';

        // Attach dynamic listeners
        tbody.querySelectorAll('.comp-step-check').forEach(chk => {
            chk.addEventListener('change', (e) => {
                const step = parseInt(e.target.dataset.step);
                let checked = [];
                try {
                    checked = JSON.parse(localStorage.getItem('tradersakti_comp_checked_steps') || '[]');
                } catch(err){}
                if (e.target.checked) {
                    if (!checked.includes(step)) checked.push(step);
                } else {
                    checked = checked.filter(s => s !== step);
                }
                localStorage.setItem('tradersakti_comp_checked_steps', JSON.stringify(checked));
                recalculateCompounding();
            });
        });

        tbody.querySelectorAll('.comp-step-growth').forEach(inp => {
            inp.addEventListener('change', (e) => {
                const step = parseInt(e.target.dataset.step);
                const val = parseFloat(e.target.value) || 0;
                let customG = {};
                try {
                    customG = JSON.parse(localStorage.getItem('tradersakti_comp_custom_growth') || '{}');
                } catch(err){}
                customG[step] = val;
                localStorage.setItem('tradersakti_comp_custom_growth', JSON.stringify(customG));
                recalculateCompounding();
            });
        });

        tbody.querySelectorAll('.comp-step-trades').forEach(inp => {
            inp.addEventListener('change', (e) => {
                const step = parseInt(e.target.dataset.step);
                const val = parseInt(e.target.value) || 1;
                let customT = {};
                try {
                    customT = JSON.parse(localStorage.getItem('tradersakti_comp_custom_trades') || '{}');
                } catch(err){}
                customT[step] = val;
                localStorage.setItem('tradersakti_comp_custom_trades', JSON.stringify(customT));
                recalculateCompounding();
            });
        });

        tbody.querySelectorAll('.comp-step-note').forEach(inp => {
            inp.addEventListener('change', (e) => {
                const step = parseInt(e.target.dataset.step);
                const val = e.target.value;
                let customN = {};
                try {
                    customN = JSON.parse(localStorage.getItem('tradersakti_comp_custom_notes') || '{}');
                } catch(err){}
                customN[step] = val;
                localStorage.setItem('tradersakti_comp_custom_notes', JSON.stringify(customN));
            });
        });
    }

    // --- Risk & MM Calculator ---
    function recalculateRiskAndMM() {
        const capitalInput = document.getElementById('risk-input-capital');
        const riskPctInput = document.getElementById('risk-input-risk-pct');
        const rrInput = document.getElementById('risk-input-rr');
        const entryInput = document.getElementById('risk-input-entry');
        const slInput = document.getElementById('risk-input-sl');
        const consecInput = document.getElementById('mm-input-consecutive-losses');
        const maxLossInput = document.getElementById('mm-input-max-losses');

        const capital = parseFloat(capitalInput.value) || 0;
        const riskPct = parseFloat(riskPctInput.value) || 0;
        const rr = parseFloat(rrInput.value) || 0;
        const entry = parseFloat(entryInput.value) || 0;
        const sl = parseFloat(slInput.value) || 0;
        const consec = parseInt(consecInput.value) || 0;
        const maxLoss = parseInt(maxLossInput.value) || 5;

        localStorage.setItem('tradersakti_risk_capital', capital);
        localStorage.setItem('tradersakti_risk_pct', riskPct);
        localStorage.setItem('tradersakti_risk_rr', rr);
        localStorage.setItem('tradersakti_risk_entry', entry);
        localStorage.setItem('tradersakti_risk_sl', sl);
        localStorage.setItem('tradersakti_risk_consec', consec);
        localStorage.setItem('tradersakti_risk_max_loss', maxLoss);

        const riskAmount = capital * (riskPct / 100);
        const targetProfit = riskAmount * rr;
        document.getElementById('risk-display-amount').textContent = `Rp ${formatRp(riskAmount)}`;
        document.getElementById('risk-display-target-profit').textContent = `Rp ${formatRp(targetProfit)}`;

        const shareRisk = entry - sl;
        const shareRiskPct = entry > 0 ? (shareRisk / entry) * 100 : 0;
        
        let shares = 0;
        let lots = 0;
        let requiredCap = 0;
        let allocationPct = 0;

        if (shareRisk > 0) {
            shares = riskAmount / shareRisk;
            lots = Math.floor(shares / 100);
            requiredCap = entry * lots * 100;
            allocationPct = capital > 0 ? (requiredCap / capital) * 100 : 0;
            
            document.getElementById('risk-display-share-risk').textContent = `Rp ${formatRp(shareRisk)} (${shareRiskPct.toFixed(2)}%)`;
            document.getElementById('risk-display-shares').textContent = `${Math.round(shares).toLocaleString('id-ID')} lembar`;
            document.getElementById('risk-display-lots').textContent = `${lots} Lot`;
            document.getElementById('risk-display-required-cap').textContent = `Rp ${formatRp(requiredCap)}`;
            document.getElementById('risk-display-allocation-pct').textContent = `${allocationPct.toFixed(2)}% dari modal`;
        } else {
            document.getElementById('risk-display-share-risk').textContent = `–`;
            document.getElementById('risk-display-shares').textContent = `0 lembar`;
            document.getElementById('risk-display-lots').textContent = `0 Lot`;
            document.getElementById('risk-display-required-cap').textContent = `Rp 0`;
            document.getElementById('risk-display-allocation-pct').textContent = `0.00% dari modal`;
        }

        const warningContainer = document.getElementById('risk-warning-container');
        let warnings = [];
        if (riskPct > 2) {
            warnings.push("⚠️ <strong>Peringatan Risiko Tinggi:</strong> Risiko per trade di atas 2% sangat berbahaya untuk kelangsungan modal jangka panjang.");
        }
        if (entry > 0 && sl >= entry) {
            warnings.push("⚠️ <strong>Peringatan Stop Loss:</strong> Harga Stop Loss harus lebih rendah dari harga Entry.");
        }
        if (allocationPct > 100) {
            warnings.push("⚠️ <strong>Peringatan Over-Allocation:</strong> Dana yang dibutuhkan melebihi modal Anda saat ini. Kecilkan ukuran lot atau persempit stop loss.");
        }
        
        if (warnings.length > 0) {
            warningContainer.innerHTML = warnings.join('<br>');
            warningContainer.classList.remove('hidden');
        } else {
            warningContainer.classList.add('hidden');
        }

        const lossBanner = document.getElementById('mm-loss-warning-banner');
        if (consec >= maxLoss) {
            lossBanner.classList.remove('hidden');
        } else {
            lossBanner.classList.add('hidden');
        }

        const projTarget = parseFloat(document.getElementById('mm-projection-target').value) || 2000000000;
        const projGrowth = parseFloat(document.getElementById('mm-projection-growth').value) || 10.0;
        
        localStorage.setItem('tradersakti_proj_target', projTarget);
        localStorage.setItem('tradersakti_proj_growth', projGrowth);

        const projMonthsEl = document.getElementById('mm-projection-months-needed');
        if (capital > 0 && projGrowth > 0 && projTarget > capital) {
            const months = Math.log(projTarget / capital) / Math.log(1 + (projGrowth / 100));
            projMonthsEl.textContent = `${Math.ceil(months)} Bulan`;
        } else {
            projMonthsEl.textContent = `–`;
        }

        const scenarioConfig = [
            { key: 'cons', growth: 0.05 },
            { key: 'mod', growth: 0.10 },
            { key: 'aggr', growth: 0.15 }
        ];

        scenarioConfig.forEach(sc => {
            const mEl = document.getElementById(`scenario-months-${sc.key}`);
            const vEl = document.getElementById(`scenario-val-${sc.key}`);
            if (mEl && vEl) {
                if (capital > 0 && projTarget > capital) {
                    const months = Math.ceil(Math.log(projTarget / capital) / Math.log(1 + sc.growth));
                    mEl.textContent = `${months} bulan`;
                    vEl.textContent = `Rp ${formatRp(projTarget)}`;
                } else {
                    mEl.textContent = `–`;
                    vEl.textContent = `Rp ${formatRp(projTarget)}`;
                }
            }
        });
    }

    function initAffirmations() {
        const checks = [
            document.getElementById('affirm-1'),
            document.getElementById('affirm-2'),
            document.getElementById('affirm-3'),
            document.getElementById('affirm-4'),
            document.getElementById('affirm-5')
        ];

        checks.forEach((chk, idx) => {
            if (chk) {
                const saved = localStorage.getItem(`tradersakti_affirm_${idx + 1}`) === 'true';
                chk.checked = saved;
                chk.addEventListener('change', () => {
                    localStorage.setItem(`tradersakti_affirm_${idx + 1}`, chk.checked);
                });
            }
        });
    }

    // --- Checklist Hub ---
    window.switchChecklistType = function(type) {
        localStorage.setItem('tradersakti_chk_type', type);
        
        const btn12 = document.getElementById('btn-chk-type-12');
        const btn30 = document.getElementById('btn-chk-type-30');
        const title = document.getElementById('checklist-title');
        const desc = document.getElementById('checklist-desc');

        if (type === 12) {
            if (btn12) btn12.className = 'btn primary';
            if (btn30) btn30.className = 'btn secondary';
            if (title) title.textContent = '12 Poin Wajib Sebelum Entry (Anti Boncos 24 Jam)';
            if (desc) desc.textContent = 'Instruksi: Pilih centang pada kolom Checklist. ENTRY AMAN jika seluruh poin terpenuhi.';
        } else {
            if (btn12) btn12.className = 'btn secondary';
            if (btn30) btn30.className = 'btn primary';
            if (title) title.textContent = '30 Checklist Toolkit (Trader Sakti Toolkit)';
            if (desc) desc.textContent = 'Instruksi: Evaluasi entry setup menggunakan toolkit lengkap. Semakin banyak poin tercentang, semakin aman.';
        }

        renderChecklist();
    };

    function renderChecklist() {
        const type = parseInt(localStorage.getItem('tradersakti_chk_type') || '12');
        const list = type === 12 ? tradersakti_checklist_12 : tradersakti_checklist_30;
        const container = document.getElementById('checklist-items-container');
        if (!container) return;

        container.innerHTML = '';

        let checkedIndices = [];
        try {
            checkedIndices = JSON.parse(localStorage.getItem(`tradersakti_checked_items_${type}`) || '[]');
        } catch(e){}

        list.forEach(item => {
            const isChecked = checkedIndices.includes(item.no);
            const card = document.createElement('div');
            card.className = `checklist-item ${isChecked ? 'checked' : ''}`;
            card.dataset.no = item.no;

            const expText = item.explanation || item.note || '';

            card.innerHTML = `
                <input type="checkbox" class="checklist-item-checkbox" ${isChecked ? 'checked' : ''}>
                <div class="checklist-item-content">
                    <span class="checklist-item-title">${item.point}</span>
                    ${expText ? `<span class="checklist-item-explanation">${expText}</span>` : ''}
                </div>
            `;

            card.addEventListener('click', (e) => {
                if (e.target.tagName === 'INPUT') {
                    toggleChecklistItem(item.no, e.target.checked);
                    return;
                }
                const chk = card.querySelector('.checklist-item-checkbox');
                chk.checked = !chk.checked;
                toggleChecklistItem(item.no, chk.checked);
            });

            container.appendChild(card);
        });

        updateChecklistVerdict();
    }

    function toggleChecklistItem(no, isChecked) {
        const type = parseInt(localStorage.getItem('tradersakti_chk_type') || '12');
        let checkedIndices = [];
        try {
            checkedIndices = JSON.parse(localStorage.getItem(`tradersakti_checked_items_${type}`) || '[]');
        } catch(e){}

        if (isChecked) {
            if (!checkedIndices.includes(no)) checkedIndices.push(no);
        } else {
            checkedIndices = checkedIndices.filter(n => n !== no);
        }

        localStorage.setItem(`tradersakti_checked_items_${type}`, JSON.stringify(checkedIndices));
        renderChecklist();
    }

    function updateChecklistVerdict() {
        const type = parseInt(localStorage.getItem('tradersakti_chk_type') || '12');
        const list = type === 12 ? tradersakti_checklist_12 : tradersakti_checklist_30;
        
        let checkedIndices = [];
        try {
            checkedIndices = JSON.parse(localStorage.getItem(`tradersakti_checked_items_${type}`) || '[]');
        } catch(e){}

        const checkedCount = checkedIndices.filter(no => list.some(item => item.no === no)).length;
        const totalCount = list.length;
        const percentage = totalCount > 0 ? Math.round((checkedCount / totalCount) * 100) : 0;

        document.getElementById('checklist-progress-text').textContent = `${checkedCount} / ${totalCount} (${percentage}%)`;
        
        const progressBar = document.getElementById('checklist-progress-bar');
        progressBar.style.width = `${percentage}%`;

        if (percentage >= 80) {
            progressBar.style.background = 'var(--color-buy)';
        } else if (percentage >= 50) {
            progressBar.style.background = '#fbbf24';
        } else {
            progressBar.style.background = 'var(--color-sell)';
        }

        const verdictCard = document.getElementById('checklist-verdict-card');
        const verdictStatus = document.getElementById('checklist-verdict-status');
        const verdictTip = document.getElementById('checklist-verdict-tip');

        verdictStatus.className = '';
        
        if (type === 12) {
            if (percentage === 100) {
                verdictStatus.textContent = 'ENTRY AMAN ✅';
                verdictStatus.classList.add('verdict-safe');
                verdictTip.innerHTML = `<strong>Kondisi ideal!</strong> 12 poin penting perlindungan dana terpenuhi. Rencana trade siap dieksekusi.`;
            } else {
                verdictStatus.textContent = 'ENTRY BAHAYA ❌';
                verdictStatus.classList.add('verdict-danger');
                verdictTip.innerHTML = `Centang seluruh <strong>12 poin wajib</strong> sebelum entry untuk mencegah kerugian impulsif! (${12 - checkedCount} poin lagi)`;
            }
        } else {
            if (percentage >= 80) {
                verdictStatus.textContent = 'ENTRY AMAN ✅';
                verdictStatus.classList.add('verdict-safe');
                verdictTip.innerHTML = `Setup A+ Terdeteksi! <strong>${percentage}%</strong> kriteria terpenuhi. Selalu gunakan stop loss.`;
            } else if (percentage >= 50) {
                verdictStatus.textContent = 'TUNGGU SETUP ⚠️';
                verdictStatus.classList.add('verdict-warning');
                verdictTip.innerHTML = `Skor: <strong>${percentage}%</strong>. Disarankan menunggu konfirmasi tren lebih lanjut atau pending order aman.`;
            } else {
                verdictStatus.textContent = 'ENTRY BAHAYA ❌';
                verdictStatus.classList.add('verdict-danger');
                verdictTip.innerHTML = `Kriteria entry sangat rendah (<strong>${percentage}%</strong>). Hindari masuk market sekarang.`;
            }
        }
    }

    // --- Sharia Predictor Engine ---
    let predictorInitialized = false;

    function initShariaPredictor() {
        if (predictorInitialized) return;
        predictorInitialized = true;

        const input = document.getElementById('pred-input-ticker');
        const btn = document.getElementById('btn-run-prediction');
        const quickBtns = document.querySelectorAll('.pred-quick-ticker');

        if (btn && input) {
            btn.addEventListener('click', () => {
                const ticker = input.value.trim().toUpperCase();
                if (ticker) {
                    runShariaPrediction(ticker);
                } else {
                    alert('Silakan masukkan ticker saham terlebih dahulu.');
                }
            });

            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const ticker = input.value.trim().toUpperCase();
                    if (ticker) {
                        runShariaPrediction(ticker);
                    } else {
                        alert('Silakan masukkan ticker saham terlebih dahulu.');
                    }
                }
            });
        }

        quickBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const ticker = btn.textContent.trim().toUpperCase();
                if (input) input.value = ticker;
                runShariaPrediction(ticker);
            });
        });

        // Load last searched ticker
        const lastTicker = localStorage.getItem('tradersakti_predictor_last_ticker');
        if (lastTicker) {
            if (input) input.value = lastTicker;
            runShariaPrediction(lastTicker);
        }
    }

    async function runShariaPrediction(ticker) {
        if (!ticker) return;
        ticker = ticker.trim().toUpperCase();

        const loading = document.getElementById('pred-loading');
        const resultContainer = document.getElementById('pred-result-container');

        if (loading) loading.classList.remove('hidden');
        if (resultContainer) resultContainer.classList.add('hidden');

        try {
            const [resDsn, resCanslim, resSignal] = await Promise.all([
                fetch(`/api/dsn_mui/${ticker}`).then(r => r.json()),
                fetch(`/api/canslim/${ticker}`).then(r => r.json()),
                fetch(`/api/signal/${ticker}`).then(r => r.json())
            ]);

            // Save to LocalStorage upon successful fetch
            localStorage.setItem('tradersakti_predictor_last_ticker', ticker);

            // Populate stock details
            const stockNameEl = document.getElementById('pred-stock-name');
            const stockPriceEl = document.getElementById('pred-stock-price');
            const stockSectorEl = document.getElementById('pred-stock-sector');
            const stockShariaStatusEl = document.getElementById('pred-stock-sharia-status');

            const name = resSignal.evaluation?.name || resDsn.ticker || ticker;
            const price = resSignal.evaluation?.current_price || resSignal.evaluation?.technical?.last_close || 0;
            const sector = resSignal.evaluation?.sector || resDsn.industry || 'N/A';
            const shariaVerdict = resDsn.verdict || 'NEEDS_MANUAL_CHECK';

            if (stockNameEl) stockNameEl.textContent = name;
            if (stockPriceEl) stockPriceEl.textContent = price > 0 ? `Rp ${formatRp(price)}` : 'N/A';
            if (stockSectorEl) stockSectorEl.textContent = sector;

            // Render Sharia compliance status
            if (stockShariaStatusEl) {
                stockShariaStatusEl.textContent = shariaVerdict;
                stockShariaStatusEl.className = ''; // Reset classes
                if (shariaVerdict === 'HALAL' || shariaVerdict === 'HALAL_TENTATIVE') {
                    stockShariaStatusEl.style.color = 'var(--color-buy)';
                } else if (shariaVerdict === 'HARAM' || shariaVerdict === 'NON-COMPLIANT') {
                    stockShariaStatusEl.style.color = 'var(--color-sell)';
                } else {
                    stockShariaStatusEl.style.color = 'var(--color-hold)';
                }
            }

            // Render Sharia checks checklist
            const chkSector = document.getElementById('pred-sharia-chk-sector');
            const chkDebt = document.getElementById('pred-sharia-chk-debt');
            const chkIncome = document.getElementById('pred-sharia-chk-income');

            if (chkSector) {
                const pass = resDsn.checks?.sector?.pass;
                const reason = resDsn.checks?.sector?.reason || '';
                chkSector.textContent = pass === true ? 'HALAL' : (pass === false ? 'HARAM' : 'GREY / CEK MANUAL');
                chkSector.style.color = pass === true ? 'var(--color-buy)' : (pass === false ? 'var(--color-sell)' : 'var(--color-hold)');
                chkSector.title = reason;
            }

            if (chkDebt) {
                const pass = resDsn.checks?.debt?.pass;
                const val = resDsn.checks?.debt?.value;
                const reason = resDsn.checks?.debt?.reason || '';
                chkDebt.textContent = pass === true ? `Lolos (${val}%)` : (pass === false ? `Gagal (${val}%)` : 'N/A (Cek Manual)');
                chkDebt.style.color = pass === true ? 'var(--color-buy)' : (pass === false ? 'var(--color-sell)' : 'var(--color-hold)');
                chkDebt.title = reason;
            }

            if (chkIncome) {
                const pass = resDsn.checks?.non_halal_income?.pass;
                const val = resDsn.checks?.non_halal_income?.value;
                const reason = resDsn.checks?.non_halal_income?.reason || '';
                chkIncome.textContent = pass === true ? `Lolos (${val}%)` : (pass === false ? `Gagal (${val}%)` : 'N/A (Cek Manual)');
                chkIncome.style.color = pass === true ? 'var(--color-buy)' : (pass === false ? 'var(--color-sell)' : 'var(--color-hold)');
                chkIncome.title = reason;
            }

            // Calculate Prediction Accuracy Score (0-6)
            let score = 0;

            // 1. Market Direction (IHSG Uptrend)
            const passMarket = !!(resCanslim.letters?.M?.pass);
            if (passMarket) score++;
            const chkMarket = document.getElementById('pred-accuracy-chk-market');
            if (chkMarket) {
                chkMarket.textContent = passMarket ? 'Lolos' : 'Gagal';
                chkMarket.style.color = passMarket ? 'var(--color-buy)' : 'var(--color-sell)';
                chkMarket.title = resCanslim.letters?.M?.reason || '';
            }

            // 2. EPS Growth QnQ > 25% (CANSLIM 'C')
            const passEps = !!(resCanslim.letters?.C?.pass || resSignal.evaluation?.fundamental?.detail?.eps_growth);
            if (passEps) score++;
            const chkEps = document.getElementById('pred-accuracy-chk-eps');
            if (chkEps) {
                chkEps.textContent = passEps ? 'Lolos' : 'Gagal';
                chkEps.style.color = passEps ? 'var(--color-buy)' : 'var(--color-sell)';
                chkEps.title = resCanslim.letters?.C?.reason || '';
            }

            // 3. ROE > 15% (CANSLIM 'A')
            const passRoe = !!(resSignal.evaluation?.fundamental?.detail?.roe);
            if (passRoe) score++;
            const chkRoe = document.getElementById('pred-accuracy-chk-roe');
            if (chkRoe) {
                chkRoe.textContent = passRoe ? 'Lolos' : 'Gagal';
                chkRoe.style.color = passRoe ? 'var(--color-buy)' : 'var(--color-sell)';
                chkRoe.title = resSignal.evaluation?.fundamental?.reasons_pass?.find(r => r.includes('ROE')) || 'ROE > 15%';
            }

            // 4. Trend (Price > MA20/MA50 or Golden Cross)
            const ma20 = resSignal.evaluation?.technical?.ma20 || 0;
            const ma50 = resSignal.evaluation?.technical?.ma50 || 0;
            const maCross = resSignal.evaluation?.technical?.ma_cross || '';
            const passTrend = (price > ma20 || price > ma50 || maCross === 'GOLDEN');
            if (passTrend) score++;
            const chkTrend = document.getElementById('pred-accuracy-chk-trend');
            if (chkTrend) {
                chkTrend.textContent = passTrend ? 'Lolos' : 'Gagal';
                chkTrend.style.color = passTrend ? 'var(--color-buy)' : 'var(--color-sell)';
                let trendDetails = [];
                if (price > ma20) trendDetails.push(`Harga > MA20 (${price} > ${ma20.toFixed(0)})`);
                if (price > ma50) trendDetails.push(`Harga > MA50 (${price} > ${ma50.toFixed(0)})`);
                if (maCross === 'GOLDEN') trendDetails.push(`Golden Cross (MA20 > MA50)`);
                chkTrend.title = trendDetails.join(', ') || 'Harga di bawah MA';
            }

            // 5. RSI Momentum (30 <= RSI <= 70)
            const rsi = resSignal.evaluation?.technical?.rsi;
            const passRsi = (rsi !== undefined && rsi !== null && rsi >= 30 && rsi <= 70);
            if (passRsi) score++;
            const chkRsi = document.getElementById('pred-accuracy-chk-rsi');
            if (chkRsi) {
                chkRsi.textContent = rsi !== undefined ? `${rsi.toFixed(1)} (${passRsi ? 'Sehat' : 'Overbought/Extrem'})` : 'N/A';
                chkRsi.style.color = passRsi ? 'var(--color-buy)' : 'var(--color-sell)';
                chkRsi.title = `RSI target 30-70. Real: ${rsi ? rsi.toFixed(1) : 'N/A'}`;
            }

            // 6. Volume Spike > 1.2x or Jalur 7% Score >= 1
            const volSpike = resSignal.evaluation?.technical?.volume_spike || (resCanslim.letters?.S?.value?.volume_spike) || 0;
            const jalur7Score = resSignal.evaluation?.technical?.jalur7?.score || 0;
            const passVol = (volSpike > 1.2 || jalur7Score >= 1);
            if (passVol) score++;
            const chkVol = document.getElementById('pred-accuracy-chk-vol');
            if (chkVol) {
                chkVol.textContent = passVol ? 'Lolos' : 'Gagal';
                chkVol.style.color = passVol ? 'var(--color-buy)' : 'var(--color-sell)';
                chkVol.title = `Volume Spike: ${volSpike.toFixed(2)}x (target > 1.2x), Jalur 7% Score: ${jalur7Score}/4 (target >= 1)`;
            }

            // Final Verdict calculations
            const verdictCard = document.getElementById('pred-verdict-card');
            const verdictTitle = document.getElementById('pred-verdict-title');
            const verdictScoreBadge = document.getElementById('pred-verdict-score-badge');

            // Reset classes
            verdictCard.className = '';
            verdictCard.style.boxShadow = '';
            
            let finalVerdict = '';
            let verdictClass = '';

            const isHaram = (shariaVerdict === 'HARAM' || shariaVerdict === 'NON-COMPLIANT');
            const isGrey = (shariaVerdict === 'NEEDS_MANUAL_CHECK');

            if (isHaram) {
                finalVerdict = 'AVOID / TIDAK SYARIAH';
                verdictClass = 'pred-verdict-avoid';
            } else if (isGrey) {
                finalVerdict = 'NEEDS MANUAL CHECK';
                verdictClass = 'pred-verdict-manual';
            } else {
                if (score >= 5) {
                    finalVerdict = 'STRONG BUY';
                    verdictClass = 'pred-verdict-strong-buy';
                } else if (score >= 3) {
                    finalVerdict = 'ACCUMULATE';
                    verdictClass = 'pred-verdict-accumulate';
                } else if (score >= 1) {
                    finalVerdict = 'WATCHLIST';
                    verdictClass = 'pred-verdict-watchlist';
                } else {
                    finalVerdict = 'HOLD';
                    verdictClass = 'pred-verdict-hold';
                }
            }

            if (verdictTitle) verdictTitle.textContent = finalVerdict;
            if (verdictScoreBadge) verdictScoreBadge.textContent = `Skor Akurasi: ${score}/6`;
            if (verdictCard) {
                verdictCard.classList.add(verdictClass);
            }

            if (resultContainer) resultContainer.classList.remove('hidden');

        } catch (error) {
            console.error('Error in running Sharia prediction:', error);
            alert(`Gagal menganalisis ticker ${ticker}. Silakan pastikan ticker valid dan server aktif.`);
        } finally {
            if (loading) loading.classList.add('hidden');
        }
    }

    // --- Hub Global Init ---
    let traderSaktiInitialized = false;

    window.initTraderSaktiHub = function() {
        if (traderSaktiInitialized) {
            return;
        }

        // Initialize Mantra Events
        const searchInput = document.getElementById('mantra-search');
        const triggerSelect = document.getElementById('mantra-filter-trigger');
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                renderMantras(searchInput.value, triggerSelect.value);
            });
        }
        if (triggerSelect) {
            triggerSelect.addEventListener('change', () => {
                renderMantras(searchInput.value, triggerSelect.value);
            });
        }

        const btnDraw = document.getElementById('btn-draw-mantra');
        const cardContainer = document.getElementById('mantra-random-card-container');
        const cardInner = document.getElementById('mantra-random-card-inner');

        function triggerRandomDraw() {
            if (cardInner.classList.contains('flipped')) {
                cardInner.classList.remove('flipped');
                setTimeout(() => {
                    const idx = Math.floor(Math.random() * tradersakti_mantras.length);
                    const m = tradersakti_mantras[idx];
                    document.getElementById('mantra-random-no').textContent = `Mantra #${m.no}`;
                    document.getElementById('mantra-random-text').textContent = m.mantra;
                    document.getElementById('mantra-random-explain').textContent = m.explanation;
                    document.getElementById('mantra-random-trigger').textContent = m.trigger;
                    cardInner.classList.add('flipped');
                }, 300);
            } else {
                const idx = Math.floor(Math.random() * tradersakti_mantras.length);
                const m = tradersakti_mantras[idx];
                document.getElementById('mantra-random-no').textContent = `Mantra #${m.no}`;
                document.getElementById('mantra-random-text').textContent = m.mantra;
                document.getElementById('mantra-random-explain').textContent = m.explanation;
                document.getElementById('mantra-random-trigger').textContent = m.trigger;
                cardInner.classList.add('flipped');
            }
        }

        if (btnDraw) btnDraw.addEventListener('click', triggerRandomDraw);
        if (cardContainer) cardContainer.addEventListener('click', triggerRandomDraw);

        renderMantras();

        // Initialize Compounding Inputs
        const compCapital = localStorage.getItem('tradersakti_comp_capital');
        const compTarget = localStorage.getItem('tradersakti_comp_target');
        const compSteps = localStorage.getItem('tradersakti_comp_steps');
        const compTrades = localStorage.getItem('tradersakti_comp_trades');
        const compPreset = localStorage.getItem('tradersakti_comp_preset');

        if (compCapital !== null) document.getElementById('comp-input-modal').value = compCapital;
        if (compTarget !== null) document.getElementById('comp-input-target').value = compTarget;
        if (compSteps !== null) document.getElementById('comp-input-steps').value = compSteps;
        if (compTrades !== null) document.getElementById('comp-input-trades').value = compTrades;
        if (compPreset !== null) document.getElementById('comp-select-preset').value = compPreset;

        ['comp-input-modal', 'comp-input-target', 'comp-input-steps', 'comp-input-trades'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('change', () => {
                    let storeKey = id.replace('comp-input-', 'tradersakti_comp_');
                    if (id === 'comp-input-modal') storeKey = 'tradersakti_comp_capital';
                    else if (id === 'comp-input-target') storeKey = 'tradersakti_comp_target';
                    
                    localStorage.setItem(storeKey, el.value);
                    recalculateCompounding();
                });
            }
        });

        const presetSel = document.getElementById('comp-select-preset');
        if (presetSel) {
            presetSel.addEventListener('change', () => {
                localStorage.setItem('tradersakti_comp_preset', presetSel.value);
                recalculateCompounding();
            });
        }

        const btnResetChecks = document.getElementById('btn-comp-reset-checks');
        if (btnResetChecks) {
            btnResetChecks.addEventListener('click', () => {
                localStorage.removeItem('tradersakti_comp_checked_steps');
                recalculateCompounding();
            });
        }

        const btnResetAll = document.getElementById('btn-comp-reset-all');
        if (btnResetAll) {
            btnResetAll.addEventListener('click', () => {
                if (confirm('Apakah Anda yakin ingin mereset kalkulator compounding ke setelan awal? Semua data kustom Anda akan dihapus.')) {
                    localStorage.removeItem('tradersakti_comp_capital');
                    localStorage.removeItem('tradersakti_comp_target');
                    localStorage.removeItem('tradersakti_comp_steps');
                    localStorage.removeItem('tradersakti_comp_trades');
                    localStorage.removeItem('tradersakti_comp_preset');
                    localStorage.removeItem('tradersakti_comp_checked_steps');
                    localStorage.removeItem('tradersakti_comp_custom_growth');
                    localStorage.removeItem('tradersakti_comp_custom_trades');
                    localStorage.removeItem('tradersakti_comp_custom_notes');

                    document.getElementById('comp-input-modal').value = 50000000;
                    document.getElementById('comp-input-target').value = 2000000000;
                    document.getElementById('comp-input-steps').value = 18;
                    document.getElementById('comp-input-trades').value = 4;
                    document.getElementById('comp-select-preset').value = 'equalized';

                    recalculateCompounding();
                }
            });
        }

        recalculateCompounding();

        // Initialize Risk Inputs
        const riskCap = localStorage.getItem('tradersakti_risk_capital');
        const riskPct = localStorage.getItem('tradersakti_risk_pct');
        const riskRr = localStorage.getItem('tradersakti_risk_rr');
        const riskEntry = localStorage.getItem('tradersakti_risk_entry');
        const riskSl = localStorage.getItem('tradersakti_risk_sl');
        const riskConsec = localStorage.getItem('tradersakti_risk_consec');
        const riskMaxLoss = localStorage.getItem('tradersakti_risk_max_loss');
        const projTarget = localStorage.getItem('tradersakti_proj_target');
        const projGrowth = localStorage.getItem('tradersakti_proj_growth');

        if (riskCap !== null) document.getElementById('risk-input-capital').value = riskCap;
        if (riskPct !== null) document.getElementById('risk-input-risk-pct').value = riskPct;
        if (riskRr !== null) document.getElementById('risk-input-rr').value = riskRr;
        if (riskEntry !== null) document.getElementById('risk-input-entry').value = riskEntry;
        if (riskSl !== null) document.getElementById('risk-input-sl').value = riskSl;
        if (riskConsec !== null) document.getElementById('mm-input-consecutive-losses').value = riskConsec;
        if (riskMaxLoss !== null) document.getElementById('mm-input-max-losses').value = riskMaxLoss;
        if (projTarget !== null) document.getElementById('mm-projection-target').value = projTarget;
        if (projGrowth !== null) document.getElementById('mm-projection-growth').value = projGrowth;

        const riskIds = [
            'risk-input-capital', 'risk-input-risk-pct', 'risk-input-rr',
            'risk-input-entry', 'risk-input-sl', 'mm-input-consecutive-losses',
            'mm-input-max-losses', 'mm-projection-target', 'mm-projection-growth'
        ];

        riskIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener('change', recalculateRiskAndMM);
                el.addEventListener('keyup', recalculateRiskAndMM);
            }
        });

        const btnSync = document.getElementById('btn-sync-portfolio-risk');
        if (btnSync) {
            btnSync.addEventListener('click', () => {
                const portValText = document.getElementById('port-total-value').textContent || '';
                const parsedVal = parseRpText(portValText);
                if (parsedVal > 0) {
                    document.getElementById('risk-input-capital').value = parsedVal;
                    recalculateRiskAndMM();
                    alert(`Kas berhasil disinkronisasi dari tab Portofolio: Rp ${formatRp(parsedVal)}`);
                } else {
                    alert('Tidak dapat menyinkronkan kas: Portofolio masih kosong atau bernilai nol.');
                }
            });
        }

        recalculateRiskAndMM();
        initAffirmations();

        // Initialize Checklist
        const savedType = parseInt(localStorage.getItem('tradersakti_chk_type') || '12');
        switchChecklistType(savedType);

        const btnResetChk = document.getElementById('btn-reset-checklists');
        if (btnResetChk) {
            btnResetChk.addEventListener('click', () => {
                const type = localStorage.getItem('tradersakti_chk_type') || '12';
                localStorage.removeItem(`tradersakti_checked_items_${type}`);
                renderChecklist();
            });
        }

        // Initialize Predictor
        initShariaPredictor();

        traderSaktiInitialized = true;
    };

    // Live IDX Market Status
    function updateIDXMarketStatus() {
        const widget = document.getElementById('idx-market-status');
        if (!widget) return;

        const now = new Date();
        const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
        const wib = new Date(utc + (3600000 * 7));

        const day = wib.getDay();
        const hours = wib.getHours();
        const minutes = wib.getMinutes();
        const seconds = wib.getSeconds();
        const timeVal = hours * 3600 + minutes * 60 + seconds;

        let status = 'closed';
        let label = 'TUTUP';
        let subText = 'Bursa Tutup';

        const t0845 = 8 * 3600 + 45 * 60; // 08:45
        const t0900 = 9 * 3600;          // 09:00
        const t1130 = 11 * 3600 + 30 * 60; // 11:30
        const t1200 = 12 * 3600;          // 12:00
        const t1330 = 13 * 3600 + 30 * 60; // 13:30
        const t1400 = 14 * 3600;          // 14:00
        const t1550 = 15 * 3600 + 50 * 60; // 15:50
        const t1600 = 16 * 3600;          // 16:00
        const t1602 = 16 * 3600 + 2 * 60;  // 16:02
        const t1615 = 16 * 3600 + 15 * 60; // 16:15

        const isFriday = (day === 5);
        const limitSesi1 = isFriday ? t1130 : t1200;
        const startSesi2 = isFriday ? t1400 : t1330;
        const isWeekend = (day === 0 || day === 6);

        if (isWeekend) {
            status = 'closed';
            label = 'TUTUP (Akhir Pekan)';
            subText = 'Buka Senin 08:45 WIB';
        } else {
            if (timeVal < t0845) {
                status = 'closed';
                label = 'TUTUP';
                subText = 'Pra-Pembukaan 08:45 WIB';
            } else if (timeVal >= t0845 && timeVal < t0900) {
                status = 'break';
                label = 'PRA-PEMBUKAAN';
                subText = 'Sesi I Mulai 09:00 WIB';
            } else if (timeVal >= t0900 && timeVal < limitSesi1) {
                status = 'open';
                label = 'BUKA (Sesi I)';
                subText = `Sesi I s.d. ${isFriday ? '11:30' : '12:00'} WIB`;
            } else if (timeVal >= limitSesi1 && timeVal < startSesi2) {
                status = 'break';
                label = 'ISTIRAHAT';
                subText = `Sesi II Mulai ${isFriday ? '14:00' : '13:30'} WIB`;
            } else if (timeVal >= startSesi2 && timeVal < t1550) {
                status = 'open';
                label = 'BUKA (Sesi II)';
                subText = 'Pra-Penutupan 15:50 WIB';
            } else if (timeVal >= t1550 && timeVal < t1600) {
                status = 'break';
                label = 'PRA-PENUTUPAN';
                subText = 'Pasca-Penutupan 16:02 WIB';
            } else if (timeVal >= t1600 && timeVal < t1602) {
                status = 'break';
                label = 'PENUTUPAN';
                subText = 'Pasca-Penutupan 16:02 WIB';
            } else if (timeVal >= t1602 && timeVal < t1615) {
                status = 'break';
                label = 'PASCA-PENUTUPAN';
                subText = 'Tutup Hari 16:15 WIB';
            } else {
                status = 'closed';
                label = 'TUTUP';
                subText = 'Buka Esok Hari 08:45 WIB';
            }
        }

        const pad = (n) => String(n).padStart(2, '0');
        const timeStr = `${pad(hours)}:${pad(minutes)}:${pad(seconds)} WIB`;

        widget.innerHTML = `
            <div class="market-status-dot ${status}"></div>
            <div class="market-status-info">
                <span class="market-status-label">${label}</span>
                <span class="market-status-time">${timeStr} | ${subText}</span>
            </div>
            
            <div class="market-status-tooltip">
                <div class="market-status-tooltip-title">Jadwal Perdagangan Bursa (REG)</div>
                <div class="market-status-tooltip-row ${(!isWeekend && !isFriday && timeVal >= t0900 && timeVal < t1200) ? 'highlight' : ''}">
                    <span>Senin - Kamis Sesi I:</span>
                    <span>09:00 - 12:00 WIB</span>
                </div>
                <div class="market-status-tooltip-row ${(!isWeekend && !isFriday && timeVal >= t1330 && timeVal < t1550) ? 'highlight' : ''}">
                    <span>Senin - Kamis Sesi II:</span>
                    <span>13:30 - 15:50 WIB</span>
                </div>
                <div class="market-status-tooltip-row ${(isFriday && timeVal >= t0900 && timeVal < t1130) ? 'highlight' : ''}">
                    <span>Jumat Sesi I:</span>
                    <span>09:00 - 11:30 WIB</span>
                </div>
                <div class="market-status-tooltip-row ${(isFriday && timeVal >= t1400 && timeVal < t1550) ? 'highlight' : ''}">
                    <span>Jumat Sesi II:</span>
                    <span>14:00 - 15:50 WIB</span>
                </div>
                <div class="market-status-tooltip-row" style="margin-top:0.4rem; border-top: 1px dashed var(--panel-border); padding-top:0.3rem;">
                    <span>Pra-Pembukaan:</span>
                    <span>08:45 - 08:59 WIB</span>
                </div>
                <div class="market-status-tooltip-row">
                    <span>Pra-Penutupan:</span>
                    <span>15:50 - 16:00 WIB</span>
                </div>
                <div class="market-status-tooltip-row">
                    <span>Pasca-Penutupan:</span>
                    <span>16:02 - 16:15 WIB</span>
                </div>
            </div>
        `;
    }

    // =====================================================================
    // TAB IDX STOCK — IHSG chart, decision, portfolio, radar (reuse existing)
    // =====================================================================
    let ihsgChart = null;
    let ihsgChartData = null;

    function _formatNumberShort(n) {
        if (n == null || isNaN(n)) return '–';
        return Number(n).toLocaleString('id-ID', { maximumFractionDigits: 2 });
    }

    function loadIHSGSpot() {
        const card = document.getElementById('ihsg-spot-card');
        const ts = document.getElementById('ihsg-timestamp');
        if (!card) return;
        fetch('/api/market')
            .then(r => r.json())
            .then(data => {
                if (ts) ts.textContent = 'Terakhir: ' + new Date().toLocaleString('id-ID');
                const ihsg = (data && data.ihsg) || {};
                const status = ihsg.status || '–';
                const last = ihsg.last;
                const ma50 = ihsg.ma50;
                const delta = ihsg.delta_vs_ma50;
                const cls = (delta != null && delta >= 0) ? 'text-positive' : 'text-negative';
                card.innerHTML = `
                    <div class="spot-card glass-panel" style="padding:1rem; text-align:center;">
                        <div style="font-size:0.75rem; color:var(--text-secondary);">IHSG (^JKSE)</div>
                        <div style="font-size:1.5rem; font-weight:700;">${_formatNumberShort(last)}</div>
                        <div class="${cls}" style="font-size:0.85rem;">${delta != null ? (delta >= 0 ? '+' : '') + delta.toFixed(2) + '% vs MA50' : '–'}</div>
                    </div>
                    <div class="spot-card glass-panel" style="padding:1rem; text-align:center;">
                        <div style="font-size:0.75rem; color:var(--text-secondary);">MA-50</div>
                        <div style="font-size:1.5rem; font-weight:700;">${_formatNumberShort(ma50)}</div>
                        <div style="font-size:0.85rem; color:var(--text-secondary);">Trend reference</div>
                    </div>
                    <div class="spot-card glass-panel" style="padding:1rem; text-align:center;">
                        <div style="font-size:0.75rem; color:var(--text-secondary);">Status Pasar</div>
                        <div style="font-size:1.25rem; font-weight:700;">${status}</div>
                        <div style="font-size:0.85rem; color:var(--text-secondary);">CAN SLIM "M"</div>
                    </div>
                `;
            })
            .catch(() => {
                card.innerHTML = '<div class="text-center text-negative" style="grid-column: span 3;">Gagal memuat data IHSG</div>';
            });
    }

    function _renderLineChart(canvasId, labels, dataset, label, color) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return null;
        const ctx = canvas.getContext('2d');
        return new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: label,
                    data: dataset,
                    borderColor: color,
                    backgroundColor: color + '22',
                    borderWidth: 2,
                    fill: true,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    tension: 0.1,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: { legend: { display: true, labels: { color: '#cbd5e1' } } },
                scales: {
                    x: { ticks: { color: '#94a3b8', maxTicksLimit: 12 }, grid: { color: 'rgba(255,255,255,0.04)' } },
                    y: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.04)' } }
                }
            }
        });
    }

    function loadIHSGChart(days = 'all') {
        const period = days === 'all' || days >= 300 ? '1y' : (days >= 60 ? '6mo' : '3mo');
        fetch(`/api/gold/history?ticker=^JKSE&period=${period}`).catch(() => null); // pre-warm; ignore
        // Tetap pakai endpoint history kita sendiri: gunakan /api/us/index/JKSE? No, IHSG bisa lewat backtest endpoint atau cache
        // Fallback: pakai endpoint US index (kebetulan generic — fetch yfinance via cache)
        fetch(`/api/us/index/JKSE?period=${period}`)
            .then(r => r.json())
            .then(data => {
                if (!data.ok || !data.data) {
                    return;
                }
                ihsgChartData = data.data;
                const labels = data.data.map(d => d.date);
                const closes = data.data.map(d => d.close);
                if (ihsgChart) ihsgChart.destroy();
                ihsgChart = _renderLineChart('chart-ihsg-history', labels, closes, 'IHSG Close', '#22c55e');
            });
    }

    window.zoomIHSGChart = function(days) {
        document.querySelectorAll('[id^="btn-ihsg-zoom-"]').forEach(b => b.classList.remove('active'));
        const targetBtn = days === 'all' ? document.getElementById('btn-ihsg-zoom-all') :
                          days === 7 ? document.getElementById('btn-ihsg-zoom-7d') :
                          days === 30 ? document.getElementById('btn-ihsg-zoom-30d') :
                          document.getElementById('btn-ihsg-zoom-1y');
        if (targetBtn) targetBtn.classList.add('active');

        if (!ihsgChartData || !ihsgChart) return loadIHSGChart(days);
        const sliced = days === 'all' ? ihsgChartData : ihsgChartData.slice(-days);
        ihsgChart.data.labels = sliced.map(d => d.date);
        ihsgChart.data.datasets[0].data = sliced.map(d => d.close);
        ihsgChart.update();
    };

    window.loadIDXStockTab = function() {
        loadIHSGSpot();
        loadIHSGChart('all');
        // Reuse existing loaders untuk decision, portfolio, prospects, ranking
        if (typeof loadDecisions === 'function') loadDecisions();
        if (typeof fetchPortfolio === 'function') fetchPortfolio();
        if (typeof fetchProspects === 'function') fetchProspects();
    };

    // =====================================================================
    // TAB US STOCK — chart indeks NDX/SPX, universe, portfolio, top5
    // =====================================================================
    let usIndexChart = null;
    let usIndexChartData = null;
    let currentUSIndex = 'GSPC';

    function loadUSMarketStatus() {
        const badge = document.getElementById('us-market-badge');
        const ts = document.getElementById('us-timestamp');
        if (!badge) return;
        fetch('/api/us/market_status')
            .then(r => r.json())
            .then(s => {
                if (badge) badge.textContent = 'SESI: ' + (s.badge || '?');
                if (ts) ts.textContent = `ET: ${s.now_et || '–'} | WIB: ${s.now_wib || '–'}`;
            }).catch(() => {});
    }

    function loadUSIndexSpot() {
        const wrap = document.getElementById('us-index-spot-cards');
        if (!wrap) return;
        const indices = [
            { sym: 'GSPC', label: 'S&P 500', color: '#3b82f6' },
            { sym: 'IXIC', label: 'NASDAQ', color: '#a855f7' },
            { sym: 'DJI', label: 'Dow Jones', color: '#f59e0b' },
        ];
        wrap.innerHTML = indices.map(i =>
            `<div class="spot-card glass-panel" id="us-spot-${i.sym}" style="padding:1rem; text-align:center;">
                <div style="font-size:0.75rem; color:var(--text-secondary);">${i.label} (^${i.sym})</div>
                <div style="font-size:1.5rem; font-weight:700;" id="us-spot-${i.sym}-price">…</div>
                <div style="font-size:0.85rem;" id="us-spot-${i.sym}-change">…</div>
             </div>`
        ).join('');
        indices.forEach(i => {
            fetch(`/api/us/index/${i.sym}?period=5d`)
                .then(r => r.json())
                .then(d => {
                    if (!d.ok || !d.data || d.data.length === 0) return;
                    const last = d.data[d.data.length - 1].close;
                    const prev = d.data.length >= 2 ? d.data[d.data.length - 2].close : last;
                    const change = ((last - prev) / prev) * 100;
                    const cls = change >= 0 ? 'text-positive' : 'text-negative';
                    const priceEl = document.getElementById(`us-spot-${i.sym}-price`);
                    const chgEl = document.getElementById(`us-spot-${i.sym}-change`);
                    if (priceEl) priceEl.textContent = _formatNumberShort(last);
                    if (chgEl) {
                        chgEl.textContent = (change >= 0 ? '+' : '') + change.toFixed(2) + '%';
                        chgEl.className = cls;
                    }
                }).catch(() => {});
        });
    }

    window.loadUSIndexChart = function(sym) {
        currentUSIndex = sym || currentUSIndex || 'GSPC';
        fetch(`/api/us/index/${currentUSIndex}?period=1y`)
            .then(r => r.json())
            .then(data => {
                if (!data.ok || !data.data) return;
                usIndexChartData = data.data;
                const labels = data.data.map(d => d.date);
                const closes = data.data.map(d => d.close);
                if (usIndexChart) usIndexChart.destroy();
                const color = currentUSIndex === 'GSPC' ? '#3b82f6'
                            : currentUSIndex === 'IXIC' ? '#a855f7'
                            : currentUSIndex === 'NDX'  ? '#06b6d4'
                            : '#f59e0b';
                usIndexChart = _renderLineChart('chart-us-index-history', labels, closes, data.symbol + ' Close', color);
            }).catch(() => {});
    };

    window.zoomUSIndexChart = function(days) {
        document.querySelectorAll('[id^="btn-usindex-zoom-"]').forEach(b => b.classList.remove('active'));
        const targetBtn = days === 'all' ? document.getElementById('btn-usindex-zoom-all') :
                          days === 7 ? document.getElementById('btn-usindex-zoom-7d') :
                          days === 30 ? document.getElementById('btn-usindex-zoom-30d') :
                          document.getElementById('btn-usindex-zoom-1y');
        if (targetBtn) targetBtn.classList.add('active');
        if (!usIndexChartData || !usIndexChart) return loadUSIndexChart(currentUSIndex);
        const sliced = days === 'all' ? usIndexChartData : usIndexChartData.slice(-days);
        usIndexChart.data.labels = sliced.map(d => d.date);
        usIndexChart.data.datasets[0].data = sliced.map(d => d.close);
        usIndexChart.update();
    };

    function loadUSMasterTable() {
        const tbody = document.getElementById('tbody-us-master');
        if (!tbody) return;
        fetch('/api/us/master')
            .then(r => r.json())
            .then(d => {
                if (!d.data || d.data.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="9" class="text-center" style="color:var(--text-secondary)">
                        ${d.note || 'Belum ada data. Klik "Build Master" di atas.'}
                    </td></tr>`;
                    return;
                }
                tbody.innerHTML = d.data.map(r => {
                    const stClass = r['AAOIFI Status'] === 'PASS' ? 'text-positive'
                                  : r['AAOIFI Status'] === 'FAIL' ? 'text-negative'
                                  : 'text-secondary';
                    return `<tr>
                        <td><strong>${r.Ticker}</strong></td>
                        <td>${r['Nama Perusahaan'] || ''}</td>
                        <td>${r.Sektor || ''}</td>
                        <td>${r.MarketCap || ''}</td>
                        <td>$${r.MP || '–'}</td>
                        <td>${r.PER || '–'}</td>
                        <td>${r.ROE || '–'}</td>
                        <td>${r['Dividend Yield'] || '–'}</td>
                        <td class="${stClass}" title="${r['AAOIFI Reason'] || ''}">${r['AAOIFI Status']}</td>
                    </tr>`;
                }).join('');
            }).catch(() => {
                tbody.innerHTML = '<tr><td colspan="9" class="text-center text-negative">Gagal memuat master US</td></tr>';
            });
    }

    function loadUSPortfolio() {
        const tbody = document.getElementById('tbody-portfolio-us');
        if (!tbody) return;
        fetch('/api/us/portfolio')
            .then(r => r.json())
            .then(arr => {
                if (!arr || arr.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" class="text-center" style="color:var(--text-secondary)">Belum ada saham US di portfolio</td></tr>';
                    return;
                }
                tbody.innerHTML = arr.map(p => {
                    const cls = p.pnl >= 0 ? 'text-positive' : 'text-negative';
                    return `<tr>
                        <td><strong>${p.ticker}</strong></td>
                        <td>$${p.harga_beli.toFixed(2)}</td>
                        <td>$${p.sekarang.toFixed(2)}</td>
                        <td class="${cls}">${p.pnl >= 0 ? '+' : ''}${p.pnl.toFixed(2)}%</td>
                        <td><button class="btn text-btn" onclick="deleteUSStock('${p.ticker}')" title="Hapus">🗑</button></td>
                    </tr>`;
                }).join('');
            });
    }

    function loadUSTop5() {
        const ol = document.getElementById('us-top5-list');
        if (!ol) return;
        fetch('/api/us/top5')
            .then(r => r.json())
            .then(d => {
                if (!d.data || d.data.length === 0) {
                    ol.innerHTML = `<li style="color:var(--text-secondary);">${d.note || 'Belum ada data — build master US dulu'}</li>`;
                    return;
                }
                ol.innerHTML = d.data.map(s =>
                    `<li><strong>${s.ticker}</strong> — ${s.name || s.sector}<br>
                     <span style="font-size:0.8rem; color:var(--text-secondary);">
                       MCap ${s.market_cap || '–'} | PER ${s.per || '–'} | ROE ${s.roe || '–'} |
                       <span class="${s.aaoifi_status === 'PASS' ? 'text-positive' : 'text-secondary'}">${s.aaoifi_status}</span>
                     </span></li>`
                ).join('');
            });
    }

    window.toggleUSAddForm = function() {
        const f = document.getElementById('add-stock-form-us');
        if (f) f.classList.toggle('hidden');
    };

    window.submitUSStock = function() {
        const ticker = document.getElementById('inp-ticker-us').value.trim().toUpperCase();
        const harga = parseFloat(document.getElementById('inp-harga-us').value);
        const lot = parseInt(document.getElementById('inp-lot-us').value);
        if (!ticker || !harga || !lot) { alert('Lengkapi ticker, harga, jumlah.'); return; }
        fetch('/api/us/portfolio', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ticker, harga, lot})
        }).then(r => r.json()).then(res => {
            if (res.success) {
                document.getElementById('inp-ticker-us').value = '';
                document.getElementById('inp-harga-us').value = '';
                document.getElementById('inp-lot-us').value = '';
                window.toggleUSAddForm();
                loadUSPortfolio();
            } else {
                alert('Gagal: ' + (res.error || '?'));
            }
        });
    };

    window.deleteUSStock = function(ticker) {
        if (!confirm(`Hapus ${ticker} dari portfolio US?`)) return;
        fetch(`/api/us/portfolio/${ticker}`, { method: 'DELETE' })
            .then(() => loadUSPortfolio());
    };

    window.triggerUSMasterBuild = function() {
        if (!confirm('Build master US (~2 menit untuk 50 ticker)?')) return;
        fetch('/api/us/build_master', { method: 'POST' })
            .then(r => r.json())
            .then(res => {
                alert(res.message || res.error || 'Started');
                setTimeout(loadUSMasterTable, 30000);  // poll after 30s
            });
    };

    // Cache memory untuk Tab US — hindari refetch saat user bolak-balik tab.
    let _usTabLastLoad = 0;
    const US_TAB_CACHE_MS = 60 * 1000;  // 1 menit; setelah itu auto-refresh saat tab dibuka lagi

    window.loadUSStockTab = function(force) {
        const now = Date.now();
        const skipRefetch = !force && (now - _usTabLastLoad) < US_TAB_CACHE_MS;
        if (skipRefetch) return;  // tab sudah recently loaded; data masih fresh
        _usTabLastLoad = now;

        // Phase 1 — ABOVE-FOLD priority (status + spot cards + chart). Browser
        // dapat ini concurrent (≤4 fetch), render skeleton instan.
        loadUSMarketStatus();
        loadUSIndexSpot();
        loadUSIndexChart(currentUSIndex);

        // Phase 2 — BELOW-FOLD defer pakai requestIdleCallback (atau setTimeout
        // fallback). Master table 50 row + portfolio + top5 = 3 fetch tambahan,
        // baru dipicu saat browser idle, supaya tidak crowding HTTP queue
        // dengan Phase 1 yang lebih penting untuk first paint.
        const _deferred = () => {
            loadUSMasterTable();
            loadUSPortfolio();
            loadUSTop5();
        };
        if (typeof window.requestIdleCallback === 'function') {
            window.requestIdleCallback(_deferred, { timeout: 1500 });
        } else {
            setTimeout(_deferred, 200);
        }
    };

    // =====================================================================
    // Dashboard: Top 5 US loader (untuk card #6 di dashboard)
    // =====================================================================
    // Cache hasil di-memory supaya re-render Dashboard tidak fetch ulang.
    let _cachedTop5US = null;
    let _cachedTop5USTime = 0;
    const TOP5_US_TTL_MS = 5 * 60 * 1000;  // 5 menit

    function renderTop5US(ol, data, note) {
        if (!data || data.length === 0) {
            ol.innerHTML = `<li style="color:var(--text-secondary);">${note || 'Build master US dulu (tab US Stock → 🔄 Build Master)'}</li>`;
            return;
        }
        ol.innerHTML = data.map(s =>
            `<li><strong>${s.ticker}</strong> — ${s.sector || ''}<br>
               <span style="font-size:0.8rem; color:var(--text-secondary);">PER ${s.per || '–'} | ROE ${s.roe || '–'}</span></li>`
        ).join('');
    }

    function _fmtUSD(n) {
        if (n == null || isNaN(n)) return '–';
        return '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 2 });
    }

    // Render rich Action Plan US — format identik dengan IDX:
    // - Header badge: "X SELL · Y BUY"
    // - Budget header: trading fund Rp + per-ticker (USD & Rp)
    // - Items: tag (SELL/BUY) | ticker | urgency | reason | sizing (lot/price/amount)
    function renderActionPlanUS(container, actionPlan) {
        if (!container) return;
        const acts = (actionPlan && actionPlan.top_actions) || [];
        const budget = actionPlan && actionPlan.budget;
        const note = actionPlan && actionPlan.note;

        if (!actionPlan || (!acts.length && !budget)) {
            container.innerHTML = `<p style="color:var(--text-secondary); font-size:0.85rem;">
                ${note || 'Belum ada rekomendasi US — pastikan master US sudah di-build.'}
            </p>`;
            return;
        }

        // Budget header
        let budgetHtml = '';
        if (budget) {
            budgetHtml = `
                <div class="action-budget">
                    <small class="muted">
                        Trading fund US: <strong>${rupiah(budget.trading_fund_rp)}</strong>
                        (≈ ${_fmtUSD(budget.trading_fund_rp / (budget.usdidr_rate || 16000))})
                        untuk ${budget.n_buy_slots} slot
                        — ${_fmtUSD(budget.bid_fund_per_ticker_usd)}/ticker
                        (${rupiah(budget.bid_fund_per_ticker_rp)})
                        @ USDIDR ${Math.round(budget.usdidr_rate || 0).toLocaleString('id-ID')}
                    </small>
                </div>
            `;
        }

        if (!acts.length) {
            container.innerHTML = budgetHtml +
                `<p class="muted" style="margin-top:0.5rem;">Tidak ada aksi prioritas US — HOLD posisi.</p>`;
            return;
        }

        const itemsHtml = acts.map(a => {
            const cls = a.action === 'SELL' ? 'sell' : (a.action === 'BUY' ? 'buy' : 'hold');
            const urgency = a.urgency || '';
            const reason = a.reason || a.reasoning || '';
            const s = a.sizing || {};
            let sizingHtml = '';
            if (s.lot > 0 && (s.amount_usd > 0 || s.amount_rp > 0)) {
                if (a.action === 'BUY') {
                    sizingHtml = `
                        <div class="action-sizing buy">
                            <div class="sizing-main">
                                💰 <strong>Beli ${s.lot} share</strong> @ ${_fmtUSD(s.price)}
                                = <strong>${_fmtUSD(s.amount_usd)}</strong>
                                <span class="muted">(${rupiah(s.amount_rp)})</span>
                            </div>
                            ${s.note ? `<div class="sizing-detail muted">${s.note}</div>` : ''}
                        </div>
                    `;
                } else if (a.action === 'SELL') {
                    sizingHtml = `
                        <div class="action-sizing sell">
                            <div class="sizing-main">
                                💸 <strong>Jual ${s.lot} share</strong> @ ${_fmtUSD(s.price)}
                                = terima <strong>${_fmtUSD(s.amount_usd)}</strong>
                                <span class="muted">(${rupiah(s.amount_rp)})</span>
                            </div>
                            ${s.note ? `<div class="sizing-detail muted">${s.note}</div>` : ''}
                        </div>
                    `;
                }
            } else if (a.action === 'BUY' && s.price > 0) {
                // Budget terlalu kecil untuk 1 full share — kasih info fractional
                sizingHtml = `
                    <div class="action-sizing buy muted">
                        <div class="sizing-detail">
                            ℹ️ Harga ${_fmtUSD(s.price)} > budget per-ticker.
                            ${a.sizing && a.sizing.note ? a.sizing.note : ''}
                            <br>Pluang support fractional dari $1 — beli sesuai budget.
                        </div>
                    </div>
                `;
            }
            return `
                <div class="dashboard-action-item ${cls}">
                    <div class="action-row">
                        <span class="action-tag ${cls}">${a.action}</span>
                        <strong class="action-ticker">${a.ticker}</strong>
                        <span class="action-urgency">${urgency}</span>
                    </div>
                    <div class="action-reason">${reason}</div>
                    ${sizingHtml}
                </div>
            `;
        }).join('');
        container.innerHTML = budgetHtml + itemsHtml;
    }

    let _cachedActionPlanUS = null;
    let _cachedActionPlanUSTime = 0;

    function _renderTop5FromCache() {
        const ol = document.getElementById('dashboard-top5-us');
        if (ol && _cachedTop5US) renderTop5US(ol, _cachedTop5US.data, _cachedTop5US.note);
    }
    function _renderActionPlanFromCache() {
        const ap = document.getElementById('dashboard-action-list-us');
        const cn = document.getElementById('dashboard-action-count');
        if (!_cachedActionPlanUS) return;
        if (ap) renderActionPlanUS(ap, _cachedActionPlanUS);
        // Badge count — gabung IDX (sudah di-set oleh loadDashboard) dengan US
        // pakai data-us-count atribut supaya tidak overwrite IDX.
        if (cn && _cachedActionPlanUS) {
            const us = `US: ${_cachedActionPlanUS.n_sell || 0}S·${_cachedActionPlanUS.n_buy || 0}B`;
            // Append US count tanpa hapus IDX kalau ada
            const existing = cn.textContent || '';
            if (!existing.includes('US:')) {
                cn.textContent = existing.trim() ? `${existing.trim()} | ${us}` : us;
            }
        }
    }

    function loadDashboardUSCards() {
        // Pakai cache memory kalau masih fresh (<5 menit) — instant render dua-duanya.
        const now = Date.now();
        const top5Fresh = _cachedTop5US && (now - _cachedTop5USTime) < TOP5_US_TTL_MS;
        const apFresh = _cachedActionPlanUS && (now - _cachedActionPlanUSTime) < TOP5_US_TTL_MS;
        if (top5Fresh && apFresh) {
            _renderTop5FromCache();
            _renderActionPlanFromCache();
            return;
        }

        const ol = document.getElementById('dashboard-top5-us');
        const ap = document.getElementById('dashboard-action-list-us');

        // Fetch Top 5 (cepat — baca CSV)
        if (!top5Fresh) {
            fetch('/api/us/top5')
                .then(r => r.json())
                .then(d => {
                    _cachedTop5US = d;
                    _cachedTop5USTime = Date.now();
                    if (ol) renderTop5US(ol, d.data, d.note);
                }).catch(() => {
                    if (ol) ol.innerHTML = '<li style="color:var(--text-secondary);">Gagal memuat Top 5 US</li>';
                });
        } else {
            _renderTop5FromCache();
        }

        // Fetch Action Plan US (lebih kompleks — sizing, USDIDR, scan portfolio)
        if (!apFresh) {
            fetch('/api/us/action_plan')
                .then(r => r.json())
                .then(d => {
                    _cachedActionPlanUS = d;
                    _cachedActionPlanUSTime = Date.now();
                    if (ap) renderActionPlanUS(ap, d);
                    _renderActionPlanFromCache();  // refresh badge count
                }).catch(() => {
                    if (ap) ap.innerHTML = '<p style="color:var(--text-secondary);">Gagal memuat rekomendasi US</p>';
                });
        } else {
            _renderActionPlanFromCache();
        }
    }

    // Backward-compat name (sebelumnya cuma render Top 5) — sekarang render KEDUA card.
    function loadDashboardTop5US() { loadDashboardUSCards(); }
    window.loadDashboardTop5US = loadDashboardTop5US;
    window.loadDashboardUSCards = loadDashboardUSCards;

    // FIRE INDEPENDENT — jangan tunggu loadDashboard yang berat. Satu fetch
    // ke /api/us/top5 mengisi DUA card sekaligus (Top 5 + Action Plan US).
    setTimeout(loadDashboardUSCards, 50);

    updateIDXMarketStatus();
    setInterval(updateIDXMarketStatus, 1000);
});
