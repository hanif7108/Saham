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
        # Penggabungan otomatis duplikat (ticker, broker, & tipe yang sama) agar data bersih
        merged = {}
        changed = False
        for r in data:
            key = (r["ticker"], r.get("broker"), r.get("type", "trading"))
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


def _price_ttl(ticker: str) -> int:
    """TTL cache harga: pendek saat sesi, panjang saat pasar tutup."""
    from datetime import datetime, time
    from app.data.provider import is_us_ticker
    is_us = is_us_ticker(ticker)
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York" if is_us else "Asia/Jakarta")
    except Exception:
        tz = None
    now = datetime.now(tz) if tz else datetime.now()
    trading_start = time(9, 30) if is_us else time(9, 0)
    trading_end = time(16, 0) if is_us else time(16, 15)
    if now.weekday() >= 5 or not (trading_start <= now.time() <= trading_end):
        return 43200  # 12 jam jika pasar tutup
    return settings.price_ttl_seconds


def _price_pair(ticker: str) -> tuple[float | None, float | None]:
    """(harga_live, prev_close) dalam satu fetch agar daily P/L efisien."""
    ttl = _price_ttl(ticker)
    current: float | None = None
    prev_close: float | None = None

    try:
        df = provider.get_history(ticker, period="10d", interval="1d", ttl=ttl)
        if df is not None and not df.empty:
            closes = df["Close"].dropna()
            if len(closes) >= 1:
                current = round(float(closes.iloc[-1]), 2)
            if len(closes) >= 2:
                prev_close = round(float(closes.iloc[-2]), 2)
    except Exception:
        pass

    # Prefer intraday last price saat sesi berjalan (lebih segar dari daily close)
    try:
        intr = provider.get_history(ticker, period="1d", interval="5m", ttl=ttl)
        if intr is not None and not intr.empty:
            live = float(intr["Close"].dropna().iloc[-1])
            if live > 0:
                current = round(live, 2)
    except Exception:
        pass

    return current, prev_close


def _current_price(ticker: str) -> float | None:
    """Harga selive mungkin: intraday 5m (cache pendek), fallback ke close harian."""
    return _price_pair(ticker)[0]


def add_position(ticker: str, lots: int, avg_price: float,
                 broker: str | None = None, type: str = "trading") -> dict[str, Any]:
    ticker = ticker.upper().strip()
    if lots <= 0 or avg_price <= 0:
        raise ValueError("lot & harga harus > 0")
    rows = _load()
    
    # Gabungkan jika posisi untuk broker & type tersebut sudah ada
    for r in rows:
        if r["ticker"] == ticker and r.get("broker") == broker and r.get("type", "trading") == type:
            total_lots = r["lots"] + int(lots)
            total_cost = (r["lots"] * r["avg_price"]) + (int(lots) * float(avg_price))
            r["lots"] = total_lots
            r["avg_price"] = round(total_cost / total_lots, 2)
            _save(rows)
            return r

    new_id = (max((r["id"] for r in rows), default=0) + 1)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    new_row = {"id": new_id, "ticker": ticker, "lots": int(lots),
               "avg_price": float(avg_price), "broker": broker, "type": type,
               "added_at": datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()}
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
    from app.data.provider import is_us_ticker, get_usd_idr_rate

    rows = _load()
    positions: list[dict[str, Any]] = []
    tot_cost = tot_value = tot_net_value = tot_total_cost = 0.0
    tot_daily_pl = 0.0
    tot_prev_value = 0.0

    trading_cost = trading_total_cost = trading_value = trading_net_value = 0.0
    investasi_cost = investasi_total_cost = investasi_value = investasi_net_value = 0.0

    # Pemuatan harga + prev_close paralel
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(rows)))) as executor:
        price_pairs = list(executor.map(lambda r: _price_pair(r["ticker"]), rows))

    usd_rate = get_usd_idr_rate()

    for idx, r in enumerate(rows):
        fee_buy, fee_sell = accounts.fees_for(r.get("broker"))
        ticker = r["ticker"]
        is_us = is_us_ticker(ticker)
        rate = usd_rate if is_us else 1.0
        shares_multiplier = 1 if is_us else MM.SHARES_PER_LOT

        shares = r["lots"] * shares_multiplier
        gross_cost = shares * r["avg_price"]
        buy_fee = gross_cost * fee_buy / 100
        total_cost = gross_cost + buy_fee                       # modal riil (termasuk biaya beli)
        cur, prev_close = price_pairs[idx]
        value = shares * cur if cur is not None else None       # nilai pasar kotor
        sell_fee = (value * fee_sell / 100) if value is not None else None
        net_value = (value - sell_fee) if value is not None else None   # hasil bersih bila dijual
        pl = (value - gross_cost) if value is not None else None        # P/L kotor (harga saja)
        pl_pct = round(pl / gross_cost * 100, 2) if (pl is not None and gross_cost) else None
        net_pl = (net_value - total_cost) if net_value is not None else None   # P/L bersih (semua biaya)
        net_pl_pct = round(net_pl / total_cost * 100, 2) if (net_pl is not None and total_cost) else None

        # P/L hari ini vs prev close (mark-to-market)
        daily_pl = daily_pl_pct = None
        if cur is not None and prev_close and prev_close > 0:
            daily_pl = shares * (cur - prev_close)
            daily_pl_pct = round((cur - prev_close) / prev_close * 100, 2)
            tot_daily_pl += daily_pl * rate
            tot_prev_value += shares * prev_close * rate

        # harga impas (break-even)
        if shares and fee_sell < 100:
            be_val = total_cost / (shares * (1 - fee_sell / 100))
            break_even = round(be_val, 2) if is_us else round(be_val)
        else:
            break_even = None

        compliant = sharia_screening.screen_sharia(ticker)["compliant"]

        # Sum in IDR (convert if US)
        tot_cost += gross_cost * rate
        tot_total_cost += total_cost * rate
        if value is not None:
            tot_value += value * rate
            tot_net_value += net_value * rate

        p_type = r.get("type", "trading")
        if p_type == "investasi":
            investasi_cost += gross_cost * rate
            investasi_total_cost += total_cost * rate
            if value is not None:
                investasi_value += value * rate
                investasi_net_value += net_value * rate
        else:
            trading_cost += gross_cost * rate
            trading_total_cost += total_cost * rate
            if value is not None:
                trading_value += value * rate
                trading_net_value += net_value * rate

        positions.append({
            **r,
            "shares": shares,
            "cost": round(gross_cost, 2) if is_us else round(gross_cost),
            "total_cost": round(total_cost, 2) if is_us else round(total_cost),
            "buy_fee": round(buy_fee, 2) if is_us else round(buy_fee),
            "fee_buy_pct": fee_buy,
            "fee_sell_pct": fee_sell,
            "current_price": cur,
            "prev_close": prev_close,
            "value": round(value, 2) if (value is not None and is_us) else round(value) if value is not None else None,
            "sell_fee": round(sell_fee, 2) if (sell_fee is not None and is_us) else round(sell_fee) if sell_fee is not None else None,
            "net_value": round(net_value, 2) if (net_value is not None and is_us) else round(net_value) if net_value is not None else None,
            "pl": round(pl, 2) if (pl is not None and is_us) else round(pl) if pl is not None else None,
            "pl_pct": pl_pct,
            "net_pl": round(net_pl, 2) if (net_pl is not None and is_us) else round(net_pl) if net_pl is not None else None,
            "net_pl_pct": net_pl_pct,
            "daily_pl": round(daily_pl, 2) if (daily_pl is not None and is_us) else round(daily_pl) if daily_pl is not None else None,
            "daily_pl_pct": daily_pl_pct,
            "break_even": break_even,
            "syariah": compliant,
            "type": p_type,
            "currency": "USD" if is_us else "IDR",
            "rate": rate
        })

    tot_pl = tot_value - tot_cost
    tot_net_pl = tot_net_value - tot_total_cost

    trading_net_pl = trading_net_value - trading_total_cost
    investasi_net_pl = investasi_net_value - investasi_total_cost
    daily_pl_pct = round(tot_daily_pl / tot_prev_value * 100, 2) if tot_prev_value else 0.0

    # Realized P/L dari trade yang ditutup hari ini (WIB)
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo("Asia/Jakarta")).date().isoformat()
    except Exception:
        today = datetime.now().date().isoformat()
    realized_today_pl = 0.0
    realized_today_n = 0
    try:
        from app.core import roi as roi_mod
        for t in roi_mod._load():
            closed = str(t.get("closed") or "")
            if closed.startswith(today):
                realized_today_pl += float(t.get("roi_idr") or 0)
                realized_today_n += 1
    except Exception:
        pass

    day_total_pl = tot_daily_pl + realized_today_pl

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
            "daily_pl": round(tot_daily_pl),
            "daily_pl_pct": daily_pl_pct,
            "realized_today_pl": round(realized_today_pl),
            "realized_today_n": realized_today_n,
            "day_total_pl": round(day_total_pl),
            "as_of": today,
        },
        "trading_summary": {
            "total_cost": round(trading_cost), "total_modal": round(trading_total_cost),
            "total_value": round(trading_value), "total_net_value": round(trading_net_value),
            "total_pl": round(trading_net_pl),
            "total_pl_pct": round(trading_net_pl / trading_total_cost * 100, 2) if trading_total_cost else 0,
            "jumlah_posisi": len([p for p in positions if p["type"] == "trading"]),
        },
        "investasi_summary": {
            "total_cost": round(investasi_cost), "total_modal": round(investasi_total_cost),
            "total_value": round(investasi_value), "total_net_value": round(investasi_net_value),
            "total_pl": round(investasi_net_pl),
            "total_pl_pct": round(investasi_net_pl / investasi_total_cost * 100, 2) if investasi_total_cost else 0,
            "jumlah_posisi": len([p for p in positions if p["type"] == "investasi"]),
        }
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
