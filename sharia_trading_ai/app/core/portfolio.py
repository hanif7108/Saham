"""
Portofolio — tracking posisi & P/L live (harga via yfinance).

Disimpan ke JSON lokal (data_store/portfolio.json). Hanya tunai/long-only
(sesuai syariah). Posisi non-syariah ditandai sebagai peringatan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.config import BASE_DIR, MM, settings
from app.core import sharia_screening
from app.data import provider

STORE = BASE_DIR.parent / "data_store" / "portfolio.json"
STORE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> list[dict[str, Any]]:
    if not STORE.exists():
        return []
    try:
        data = json.loads(STORE.read_text())
        # Penggabungan otomatis duplikat (ticker & broker yang sama) agar data bersih
        merged = {}
        changed = False
        for r in data:
            key = (r["ticker"], r.get("broker"))
            if key in merged:
                existing = merged[key]
                total_lots = existing["lots"] + r["lots"]
                total_cost = (existing["lots"] * existing["avg_price"]) + (r["lots"] * r["avg_price"])
                existing["lots"] = total_lots
                existing["avg_price"] = round(total_cost / total_lots, 2)
                changed = True
            else:
                merged[key] = r
        if changed:
            _save(list(merged.values()))
        return list(merged.values())
    except Exception:
        return []


def _save(rows: list[dict[str, Any]]) -> None:
    STORE.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


def _current_price(ticker: str) -> float | None:
    """Harga selive mungkin: intraday 5m (cache pendek), fallback ke close harian.

    Harga posisi/jual butuh kesegaran — daily close bisa lag saat sesi berjalan.
    `price_ttl_seconds` menjaga harga ≤ beberapa menit tanpa membebani yfinance.
    """
    from datetime import datetime, time
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Asia/Jakarta")
    except Exception:
        tz = None

    now = datetime.now(tz) if tz else datetime.now()
    # IDX trading day: Mon-Fri, hours: 09:00 - 16:15 WIB
    if now.weekday() >= 5 or not (time(9, 0) <= now.time() <= time(16, 15)):
        ttl = 43200  # 12 jam jika pasar tutup
    else:
        ttl = settings.price_ttl_seconds

    try:
        intr = provider.get_history(ticker, period="1d", interval="5m", ttl=ttl)
        if intr is not None and not intr.empty:
            return round(float(intr["Close"].iloc[-1]), 2)
    except Exception:
        pass
    try:
        df = provider.get_history(ticker, period="5d", ttl=ttl)
        if df is None or df.empty:
            return None
        return round(float(df["Close"].iloc[-1]), 2)
    except Exception:
        return None


def add_position(ticker: str, lots: int, avg_price: float,
                 broker: str | None = None) -> dict[str, Any]:
    ticker = ticker.upper().strip()
    if lots <= 0 or avg_price <= 0:
        raise ValueError("lot & harga harus > 0")
    rows = _load()
    
    # Gabungkan jika posisi untuk broker tersebut sudah ada
    for r in rows:
        if r["ticker"] == ticker and r.get("broker") == broker:
            total_lots = r["lots"] + int(lots)
            total_cost = (r["lots"] * r["avg_price"]) + (int(lots) * float(avg_price))
            r["lots"] = total_lots
            r["avg_price"] = round(total_cost / total_lots, 2)
            _save(rows)
            return r

    new_id = (max((r["id"] for r in rows), default=0) + 1)
    new_row = {"id": new_id, "ticker": ticker, "lots": int(lots),
               "avg_price": float(avg_price), "broker": broker}
    rows.append(new_row)
    _save(rows)
    return new_row


def remove_position(pos_id: int) -> bool:
    rows = _load()
    new = [r for r in rows if r["id"] != pos_id]
    if len(new) == len(rows):
        return False
    _save(new)
    return True


def reduce_position(pos_id: int, lots_sold: int) -> Optional[int]:
    """Kurangi lot posisi (jual sebagian). Hapus bila habis. Return sisa lot (0=habis, None=tak ada)."""
    rows = _load()
    for i, r in enumerate(rows):
        if r["id"] == pos_id:
            rem = int(r["lots"]) - int(lots_sold)
            if rem <= 0:
                rows.pop(i)
                _save(rows)
                return 0
            r["lots"] = rem
            _save(rows)
            return rem
    return None


def list_positions() -> dict[str, Any]:
    from app.core import accounts  # lazy → hindari import melingkar (accounts↔portfolio)
    from concurrent.futures import ThreadPoolExecutor

    rows = _load()
    positions: list[dict[str, Any]] = []
    tot_cost = tot_value = tot_net_value = tot_total_cost = 0.0

    # Pemuatan harga secara paralel agar tidak memblokir sekuensial (terutama saat cache kosong)
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(rows)))) as executor:
        prices = list(executor.map(lambda r: _current_price(r["ticker"]), rows))

    for idx, r in enumerate(rows):
        fee_buy, fee_sell = accounts.fees_for(r.get("broker"))
        shares = r["lots"] * MM.SHARES_PER_LOT
        gross_cost = shares * r["avg_price"]
        buy_fee = gross_cost * fee_buy / 100
        total_cost = gross_cost + buy_fee                       # modal riil (termasuk biaya beli)
        cur = prices[idx]
        value = shares * cur if cur is not None else None       # nilai pasar kotor
        sell_fee = (value * fee_sell / 100) if value is not None else None
        net_value = (value - sell_fee) if value is not None else None   # hasil bersih bila dijual
        pl = (value - gross_cost) if value is not None else None        # P/L kotor (harga saja)
        pl_pct = round(pl / gross_cost * 100, 2) if (pl is not None and gross_cost) else None
        net_pl = (net_value - total_cost) if net_value is not None else None   # P/L bersih (semua biaya)
        net_pl_pct = round(net_pl / total_cost * 100, 2) if (net_pl is not None and total_cost) else None
        # harga impas (break-even): harga jual agar hasil bersih = modal riil
        break_even = round(total_cost / (shares * (1 - fee_sell / 100))) if (shares and fee_sell < 100) else None
        compliant = sharia_screening.screen_sharia(r["ticker"])["compliant"]
        tot_cost += gross_cost
        tot_total_cost += total_cost
        if value is not None:
            tot_value += value
            tot_net_value += net_value
        positions.append({
            **r, "shares": shares, "cost": round(gross_cost), "total_cost": round(total_cost),
            "buy_fee": round(buy_fee), "fee_buy_pct": fee_buy, "fee_sell_pct": fee_sell,
            "current_price": cur, "value": round(value) if value is not None else None,
            "sell_fee": round(sell_fee) if sell_fee is not None else None,
            "net_value": round(net_value) if net_value is not None else None,
            "pl": round(pl) if pl is not None else None, "pl_pct": pl_pct,
            "net_pl": round(net_pl) if net_pl is not None else None, "net_pl_pct": net_pl_pct,
            "break_even": break_even, "syariah": compliant,
        })
    tot_pl = tot_value - tot_cost
    tot_net_pl = tot_net_value - tot_total_cost
    return {
        "positions": positions,
        "summary": {
            "total_cost": round(tot_cost), "total_modal": round(tot_total_cost),
            "total_value": round(tot_value), "total_net_value": round(tot_net_value),
            "total_pl": round(tot_pl),
            "total_pl_pct": round(tot_pl / tot_cost * 100, 2) if tot_cost else 0,
            "total_net_pl": round(tot_net_pl),
            "total_net_pl_pct": round(tot_net_pl / tot_total_cost * 100, 2) if tot_total_cost else 0,
            "jumlah_posisi": len(positions),
        },
    }


def sync_broker_positions(broker: str, new_positions: list[dict[str, Any]]) -> list[str]:
    """Sinkronkan posisi portofolio untuk broker tertentu.

    - Hapus posisi broker ini yang tidak ada di new_positions.
    - Perbarui (overwrite) lot & avg_price untuk posisi yang ada.
    - Tambahkan posisi baru jika belum ada di portofolio.
    Return list ticker yang berhasil diimpor/diperbarui.
    """
    rows = _load()
    broker = broker.strip() if broker else "Profits Anywhere"

    # Kumpulkan ticker baru yang diimpor
    new_map = {p["ticker"].upper().strip(): p for p in new_positions if p.get("importable") or "lots" in p}

    # Hapus posisi broker ini yang tidak ada di new_map
    updated_rows = []
    for r in rows:
        if r.get("broker") == broker:
            if r["ticker"].upper() in new_map:
                # Simpan untuk diperbarui di bawah
                updated_rows.append(r)
        else:
            # Biarkan broker lain tidak tersentuh
            updated_rows.append(r)

    # Perbarui dan tambahkan posisi
    imported_tickers = []
    for ticker, p in new_map.items():
        lots = int(p["lots"])
        avg_price = float(p["avg_price"])
        if lots <= 0 or avg_price <= 0:
            continue

        # Cari apakah sudah ada di list updated_rows
        found = False
        for r in updated_rows:
            if r["ticker"].upper() == ticker and r.get("broker") == broker:
                r["lots"] = lots
                r["avg_price"] = avg_price
                found = True
                break
        if not found:
            new_id = (max((r["id"] for r in updated_rows), default=0) + 1)
            updated_rows.append({
                "id": new_id,
                "ticker": ticker,
                "lots": lots,
                "avg_price": avg_price,
                "broker": broker
            })
        imported_tickers.append(ticker)

    _save(updated_rows)
    return imported_tickers
