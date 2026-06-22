#!/usr/bin/env node
/**
 * tv_poll.mjs — Poller intraday TradingView via CDP untuk Sharia Trading Assistant.
 *
 * Konek ke TradingView Desktop (CDP port 9222) SATU kali, lalu loop daftar simbol:
 * set symbol → tunggu chart siap → ambil quote. Output JSON array ke stdout.
 *
 * Dipakai oleh modules/tv_collector.py (dijalankan terjadwal saat jam bursa IDX).
 * Ini Node murni (tanpa LLM) — deterministik & murah, aman untuk produksi.
 *
 * Usage:  node tv_poll.mjs "IDX:MARK,IDX:PTBA,IDX:TLKM"
 * Env:    TV_MCP_DIR   (default: /Users/hanif/Saham/tradingview-mcp)
 *         TV_SETTLE_MS (default: 700)  jeda tambahan setelah chart siap
 * Exit:   0 sukses, 2 gagal konek CDP (TradingView mati / port tutup)
 */

import { pathToFileURL } from 'node:url';
import path from 'node:path';

const MCP_DIR = process.env.TV_MCP_DIR || '/Users/hanif/Saham/tradingview-mcp';
const imp = (rel) => import(pathToFileURL(path.join(MCP_DIR, rel)).href);

const { connect, disconnect } = await imp('src/connection.js');
const { setSymbol } = await imp('src/core/chart.js');
const { getQuote } = await imp('src/core/data.js');

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const symbols = (process.argv[2] || '')
  .split(',').map((s) => s.trim()).filter(Boolean);
const settleMs = parseInt(process.env.TV_SETTLE_MS || '400', 10);
const readyMs = parseInt(process.env.TV_READY_MS || '3500', 10);

if (symbols.length === 0) {
  console.error(JSON.stringify({ fatal: 'no symbols given' }));
  process.exit(1);
}

const out = [];
try {
  await connect();
  for (const sym of symbols) {
    const rec = { symbol: sym, ts: Math.floor(Date.now() / 1000) };
    try {
      await setSymbol({ symbol: sym });
      // Polling getQuote sampai quote mencerminkan simbol baru (chart selesai switch).
      // Mengukur kesiapan via data yang dibutuhkan — bukan heuristik DOM.
      const ticker = sym.split(':').pop().toUpperCase();
      let q = null;
      const deadline = Date.now() + readyMs;
      while (Date.now() < deadline) {
        q = await getQuote({});
        if (q && q.success && String(q.symbol || '').toUpperCase().endsWith(ticker)) break;
        await sleep(120);
      }
      if (settleMs) await sleep(settleMs);
      rec.ok = !!(q && q.success && String(q.symbol || '').toUpperCase().endsWith(ticker));
      rec.quote = q;
    } catch (e) {
      rec.ok = false;
      rec.error = String((e && e.message) || e);
    }
    out.push(rec);
  }
} catch (e) {
  // Gagal konek (TradingView mati / port tutup) → exit 2 agar Python fallback ke yfinance.
  console.error(JSON.stringify({ fatal: String((e && e.message) || e) }));
  process.exit(2);
} finally {
  try { await disconnect(); } catch {}
}

process.stdout.write(JSON.stringify(out));
