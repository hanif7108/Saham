"""
Pegadaian Tring — Emas Digital Tracker
======================================
CRUD untuk transaksi tabungan emas Pegadaian.

Tipe transaksi (mirror broker_transactions.csv):
  TOPUP       — isi saldo Rp ke akun Pegadaian (belum konversi ke emas)
  BUY         — beli emas (gram bertambah, saldo Rp berkurang ATAU debit langsung)
  SELL        — jual emas (gram berkurang, saldo Rp bertambah ATAU diterima cash)
  WITHDRAWAL  — tarik saldo Rp dari akun

Schema CSV (pegadaian_transactions.csv):
  id, tanggal, tipe, gram, harga_per_gram, nominal_rp, fee_rp, catatan

Aturan akad syariah:
  - Spot (qabdh): pencatatan harus sesuai harga & berat saat transaksi terjadi.
  - Pegadaian sudah dilegitimasi DSN-MUI (Tabungan Emas berbasis Wadiah Yad Dhamanah).
"""

from __future__ import annotations

import csv
import os
import time
import uuid
from typing import Dict, List, Optional

CSV_HEADERS = [
    "id", "tanggal", "tipe", "gram", "harga_per_gram",
    "nominal_rp", "fee_rp", "catatan"
]
VALID_TYPES = {"TOPUP", "BUY", "SELL", "WITHDRAWAL"}


# ---------- I/O ---------- #
def _ensure_csv(path: str) -> None:
    """Buat CSV dengan header kalau belum ada."""
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            w.writeheader()


def load_transactions(path: str) -> List[Dict]:
    _ensure_csv(path)
    out = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Cast tipe data
            try:
                row["gram"] = float(row.get("gram") or 0)
                row["harga_per_gram"] = float(row.get("harga_per_gram") or 0)
                row["nominal_rp"] = float(row.get("nominal_rp") or 0)
                row["fee_rp"] = float(row.get("fee_rp") or 0)
            except (ValueError, TypeError):
                continue
            out.append(row)
    # Sort by tanggal descending (terbaru di atas)
    out.sort(key=lambda r: r.get("tanggal", ""), reverse=True)
    return out


def save_transactions(path: str, txs: List[Dict]) -> None:
    _ensure_csv(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        w.writeheader()
        for tx in txs:
            row = {k: tx.get(k, "") for k in CSV_HEADERS}
            w.writerow(row)


def add_transaction(path: str, tx: Dict) -> Dict:
    """Tambah satu transaksi. Return tx yang sudah di-validate + di-assign id."""
    tipe = (tx.get("tipe") or "").upper()
    if tipe not in VALID_TYPES:
        return {"error": f"Tipe transaksi tidak valid. Pakai salah satu: {sorted(VALID_TYPES)}"}

    gram = float(tx.get("gram") or 0)
    harga_per_gram = float(tx.get("harga_per_gram") or 0)
    nominal_rp = float(tx.get("nominal_rp") or 0)
    fee_rp = float(tx.get("fee_rp") or 0)

    # Validasi per tipe
    if tipe in ("BUY", "SELL"):
        if gram <= 0:
            return {"error": f"Tipe {tipe} butuh gram > 0"}
        if harga_per_gram <= 0:
            return {"error": f"Tipe {tipe} butuh harga_per_gram > 0"}
        # Auto-hitung nominal kalau user tidak isi
        if nominal_rp <= 0:
            nominal_rp = gram * harga_per_gram
    elif tipe in ("TOPUP", "WITHDRAWAL"):
        if nominal_rp <= 0:
            return {"error": f"Tipe {tipe} butuh nominal_rp > 0"}
        # Reset gram & harga supaya konsisten
        gram = 0
        harga_per_gram = 0

    new_tx = {
        "id": tx.get("id") or f"pgd_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
        "tanggal": tx.get("tanggal") or time.strftime("%Y-%m-%d"),
        "tipe": tipe,
        "gram": round(gram, 4),
        "harga_per_gram": round(harga_per_gram, 0),
        "nominal_rp": round(nominal_rp, 0),
        "fee_rp": round(fee_rp, 0),
        "catatan": (tx.get("catatan") or "").strip(),
    }

    txs = load_transactions(path)
    txs.append(new_tx)
    save_transactions(path, txs)
    return new_tx


def delete_transaction(path: str, tx_id: str) -> bool:
    txs = load_transactions(path)
    new_txs = [t for t in txs if t.get("id") != tx_id]
    if len(new_txs) == len(txs):
        return False
    save_transactions(path, new_txs)
    return True


# ---------- Aggregator ---------- #
def summarize(path: str, current_price_per_gram: float = 0.0) -> Dict:
    """
    Agregat seluruh transaksi → ringkasan portofolio Pegadaian.

    Args:
        current_price_per_gram: harga emas Pegadaian terkini (Rp/gram)

    Returns dict:
        {
          total_gram, avg_buy_price, total_invested, current_value,
          pnl_rp, pnl_pct, saldo_rp, fee_total, n_tx
        }
    """
    txs = load_transactions(path)
    total_gram_buy = 0.0
    total_gram_sell = 0.0
    total_invested_buy = 0.0   # Rp keluar untuk BUY emas
    total_received_sell = 0.0  # Rp masuk dari SELL emas
    saldo_topup = 0.0
    saldo_withdrawal = 0.0
    fee_total = 0.0

    for t in txs:
        tipe = t.get("tipe", "").upper()
        fee_total += float(t.get("fee_rp") or 0)

        if tipe == "BUY":
            total_gram_buy += float(t.get("gram") or 0)
            total_invested_buy += float(t.get("nominal_rp") or 0)
        elif tipe == "SELL":
            total_gram_sell += float(t.get("gram") or 0)
            total_received_sell += float(t.get("nominal_rp") or 0)
        elif tipe == "TOPUP":
            saldo_topup += float(t.get("nominal_rp") or 0)
        elif tipe == "WITHDRAWAL":
            saldo_withdrawal += float(t.get("nominal_rp") or 0)

    total_gram = round(total_gram_buy - total_gram_sell, 4)
    # Average buy price hanya dari BUY (gram bersih × harga) — pakai weighted average
    if total_gram_buy > 0:
        avg_buy_price = total_invested_buy / total_gram_buy
    else:
        avg_buy_price = 0.0

    # Investasi efektif yang masih nyangkut di gram (kurangi gram yang sudah di-sell)
    effective_invested = avg_buy_price * total_gram
    current_value = total_gram * current_price_per_gram if current_price_per_gram > 0 else 0.0
    pnl_rp = current_value - effective_invested if current_price_per_gram > 0 else 0.0
    pnl_pct = (pnl_rp / effective_invested * 100) if effective_invested > 0 else 0.0

    # Saldo Rp = TOPUP − WITHDRAWAL − BUY + SELL − FEE
    saldo_rp = saldo_topup - saldo_withdrawal - total_invested_buy + total_received_sell - fee_total

    return {
        "n_tx": len(txs),
        "total_gram": round(total_gram, 4),
        "total_gram_buy": round(total_gram_buy, 4),
        "total_gram_sell": round(total_gram_sell, 4),
        "avg_buy_price": round(avg_buy_price, 0),
        "effective_invested_rp": round(effective_invested, 0),
        "current_price_per_gram": round(current_price_per_gram, 0),
        "current_value_rp": round(current_value, 0),
        "pnl_rp": round(pnl_rp, 0),
        "pnl_pct": round(pnl_pct, 2),
        "saldo_rp": round(saldo_rp, 0),
        "total_invested_rp": round(total_invested_buy, 0),
        "total_received_sell_rp": round(total_received_sell, 0),
        "total_topup_rp": round(saldo_topup, 0),
        "total_withdrawal_rp": round(saldo_withdrawal, 0),
        "fee_total_rp": round(fee_total, 0),
    }


# ---------- Harga emas Pegadaian (parse dari commodity_data.json) ---------- #
def parse_pegadaian_price_per_gram(commodity_data: Dict) -> Optional[float]:
    """
    Ambil harga jual Pegadaian per gram dari output get_commodity_data().

    Strategi: pakai row gram=1 (paling akurat per-gram), fallback ke
    1000/1000 atau 100/100.
    """
    rows = (commodity_data or {}).get("antam_pegadaian_table") or []
    if not rows:
        return None

    def _parse(val):
        # "2.681.075.000" → 2681075000.0
        if not val:
            return 0.0
        try:
            return float(str(val).replace(".", "").replace(",", ".").strip())
        except Exception:
            return 0.0

    # Build lookup gram → price
    lookup = {}
    for r in rows:
        try:
            g = float(str(r.get("gram", "0")).replace(",", "."))
            p = _parse(r.get("pegadaian"))
            if g > 0 and p > 0:
                lookup[g] = p
        except Exception:
            continue

    # Pref: gram = 1 (paling jujur per-gram)
    if 1.0 in lookup:
        return round(lookup[1.0], 0)

    # Fallback: 5 / 10 / 100 / 1000 — bagi gram
    for g in (5.0, 10.0, 100.0, 1000.0):
        if g in lookup:
            return round(lookup[g] / g, 0)

    # Ambil row pertama yang ada
    g0 = next(iter(lookup))
    return round(lookup[g0] / g0, 0)
