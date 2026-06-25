"""
Akun RDN (cash) + ringkasan CASH & ASET per RDN + advice Money Management.

Tiap broker = satu RDN. Saldo cash disimpan ke data_store/accounts.json (bisa
diisi manual atau otomatis dari e-statement). Modul ini menggabungkan cash +
posisi (per broker) menjadi tampilan per-RDN, lalu memberi saran alokasi trading
sesuai metode Money Management ("MM TP") sambil MENJAGA jumlah emiten = target
(default 3) yang dikelola harian.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.config import MM, BASE_DIR, settings
from app.core import portfolio, trading_plan
from app.core.vision_import import _norm_broker

STORE = BASE_DIR.parent / "data_store" / "accounts.json"
STORE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> list[dict[str, Any]]:
    if not STORE.exists():
        return []
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return []


def _save(rows: list[dict[str, Any]]) -> None:
    STORE.write_text(json.dumps(rows, ensure_ascii=False, indent=2))


def list_accounts() -> list[dict[str, Any]]:
    return _load()


def set_account(broker: str, cash: float, rdn: Optional[str] = None,
                bank: Optional[str] = None, fee_buy_pct: Optional[float] = None,
                fee_sell_pct: Optional[float] = None,
                cash_at_broker: Optional[float] = None,
                cash_at_rdn: Optional[float] = None,
                gold_balance_grams: Optional[float] = None,
                gold_avg_price: Optional[float] = None) -> dict[str, Any]:
    """Upsert saldo cash + biaya transaksi sebuah RDN (kunci = broker, dinormalisasi)."""
    broker = _norm_broker(broker) or (broker or "").strip()
    if not broker:
        raise ValueError("broker wajib diisi")
    rows = _load()
    for r in rows:
        if r["broker"] == broker:
            r["cash"] = float(cash)
            if rdn:
                r["rdn"] = rdn
            if bank:
                r["bank"] = bank
            if fee_buy_pct is not None:
                r["fee_buy_pct"] = float(fee_buy_pct)
            if fee_sell_pct is not None:
                r["fee_sell_pct"] = float(fee_sell_pct)
            if cash_at_broker is not None:
                r["cash_at_broker"] = float(cash_at_broker)
            if cash_at_rdn is not None:
                r["cash_at_rdn"] = float(cash_at_rdn)
            if gold_balance_grams is not None:
                r["gold_balance_grams"] = float(gold_balance_grams) if gold_balance_grams > 0 else None
            if gold_avg_price is not None:
                r["gold_avg_price"] = float(gold_avg_price) if gold_avg_price > 0 else None
            _save(rows)
            return r
    new = {"id": max((r["id"] for r in rows), default=0) + 1,
           "broker": broker, "cash": float(cash), "rdn": rdn, "bank": bank,
           "fee_buy_pct": float(fee_buy_pct) if fee_buy_pct is not None else MM.FEE_BUY_PCT,
           "fee_sell_pct": float(fee_sell_pct) if fee_sell_pct is not None else MM.FEE_SELL_PCT}
    if cash_at_broker is not None:
        new["cash_at_broker"] = float(cash_at_broker)
    if cash_at_rdn is not None:
        new["cash_at_rdn"] = float(cash_at_rdn)
    if gold_balance_grams is not None and gold_balance_grams > 0:
        new["gold_balance_grams"] = float(gold_balance_grams)
    if gold_avg_price is not None and gold_avg_price > 0:
        new["gold_avg_price"] = float(gold_avg_price)
    rows.append(new)
    _save(rows)
    return new


def update_fees(broker: str, fee_buy: Optional[float] = None,
                fee_sell: Optional[float] = None) -> dict[str, Any]:
    """Set biaya transaksi sebuah RDN tanpa mengubah cash (buat baru cash=0 bila perlu)."""
    broker = _norm_broker(broker) or (broker or "").strip()
    rows = _load()
    for r in rows:
        if r["broker"] == broker:
            if fee_buy is not None:
                r["fee_buy_pct"] = float(fee_buy)
            if fee_sell is not None:
                r["fee_sell_pct"] = float(fee_sell)
            _save(rows)
            return r
    new = {"id": max((r["id"] for r in rows), default=0) + 1, "broker": broker,
           "cash": 0.0, "rdn": None, "bank": None,
           "fee_buy_pct": float(fee_buy) if fee_buy is not None else MM.FEE_BUY_PCT,
           "fee_sell_pct": float(fee_sell) if fee_sell is not None else MM.FEE_SELL_PCT}
    rows.append(new)
    _save(rows)
    return new


def adjust_cash(broker: str, delta: float) -> dict[str, Any]:
    """Tambah/kurangi saldo cash RDN sebesar delta (mis. + hasil jual, − biaya beli)."""
    broker = _norm_broker(broker) or (broker or "").strip()
    rows = _load()
    for r in rows:
        if r["broker"] == broker:
            r["cash"] = round(float(r.get("cash") or 0) + float(delta))
            _save(rows)
            return r
    return set_account(broker, max(0.0, float(delta)))


def fees_for(broker: Optional[str]) -> tuple[float, float]:
    """(biaya_beli%, biaya_jual%) untuk broker; default config bila tak tercatat."""
    broker = _norm_broker(broker) or (broker or "")
    for a in _load():
        if a["broker"] == broker:
            return (float(a.get("fee_buy_pct", MM.FEE_BUY_PCT)),
                    float(a.get("fee_sell_pct", MM.FEE_SELL_PCT)))
    return (MM.FEE_BUY_PCT, MM.FEE_SELL_PCT)


def remove_account(acc_id: int) -> bool:
    rows = _load()
    new = [r for r in rows if r["id"] != acc_id]
    if len(new) == len(rows):
        return False
    _save(new)
    return True


# --------------------------- advice Money Management --------------------------- #
def _mm_advice(cash: float, held_emiten: int, target: int,
               fee_buy: float, fee_sell: float) -> dict[str, Any]:
    """Saran alokasi trading utk satu RDN (sadar biaya), jaga jumlah emiten = target."""
    open_slots = max(0, target - held_emiten)
    roundtrip = round(fee_buy + fee_sell, 3)              # biaya pulang-pergi (beli+jual)
    if cash <= 0:
        return {"cash": round(cash), "trading_fund": 0, "per_emiten": 0,
                "held_emiten": held_emiten, "open_slots": open_slots, "deployable_now": 0,
                "fee_buy_pct": fee_buy, "fee_sell_pct": fee_sell, "roundtrip_pct": roundtrip,
                "net_profit_min_pct": round(MM.PROFIT_FUND_PCT + roundtrip, 2),
                "note": "Saldo cash RDN belum tercatat / habis. Isi saldo cash agar muncul saran alokasi."}
    mm = trading_plan.money_management(cash, target, MM.LOSS_FUND_PCT, MM.PROFIT_FUND_PCT)
    per = mm["bid_fund"]                       # = trading_fund / target emiten
    deployable = round(per * open_slots)
    # target profit MINIMAL agar BERSIH setelah biaya pulang-pergi
    net_profit_min = round(mm["profit_pct"] + roundtrip, 2)
    if open_slots == 0:
        note = (f"Portofolio sudah penuh {held_emiten}/{target} emiten. Tahan penambahan emiten baru; "
                f"sisihkan cash untuk average-down / rotasi.")
    elif held_emiten == 0:
        note = (f"Belum ada emiten. Sebar dana trading Rp {mm['trading_fund']:,} ke {target} emiten "
                f"@ Rp {per:,}/emiten (sudah termasuk jatah biaya beli {fee_buy}%).").replace(",", ".")
    else:
        note = (f"Pegang {held_emiten}/{target} · {open_slots} slot kosong. Siap deploy Rp {deployable:,} "
                f"(Rp {per:,}/emiten).").replace(",", ".")
    note += (f" Biaya: beli {fee_buy}% + jual {fee_sell}% = pulang-pergi {roundtrip}% → "
             f"target jual minimal +{net_profit_min}% agar profit {mm['profit_pct']}% BERSIH.")
    return {
        "cash": round(cash),
        "trading_fund_pct": mm["trading_fund_pct"],
        "trading_fund": mm["trading_fund"],
        "reserve_fund": round(cash - mm["trading_fund"]),
        "per_emiten": per,
        "held_emiten": held_emiten,
        "open_slots": open_slots,
        "deployable_now": deployable,
        "risk_pct": mm["risk_pct"], "profit_pct": mm["profit_pct"],
        "risk_per_bid": mm["loss_fund"], "profit_per_bid": mm["profit_fund"],
        "fee_buy_pct": fee_buy, "fee_sell_pct": fee_sell, "roundtrip_pct": roundtrip,
        "net_profit_min_pct": net_profit_min,
        "note": note,
    }


def _health(cash_pct: Optional[float], open_slots: int) -> Optional[str]:
    if cash_pct is None:
        return None
    if cash_pct >= 70 and open_slots > 0:
        return "Cash dominan & ada slot kosong → peluang deploy ke emiten berkualitas."
    if cash_pct <= 15 and open_slots == 0:
        return "Hampir seluruh ekuitas di saham (cash tipis) → fokus kelola posisi, hindari over-allocate."
    return "Alokasi cash/aset seimbang."


# --------------------------- breakdown per RDN --------------------------- #
def breakdown() -> dict[str, Any]:
    from app.core import commodities
    
    # Ambil harga emas per gram IDR
    gold_price_g = None
    try:
        for item in commodities.commodities()["emas_komoditas"]:
            if "gram" in item["unit"]:
                gold_price_g = item["harga"]
                break
    except Exception:
        pass

    accounts = {a["broker"]: a for a in _load()}
    positions = portfolio.list_positions()["positions"]
    target = max(1, int(settings.target_holdings))

    groups: dict[str, list[dict]] = {}
    for p in positions:
        groups.setdefault(p.get("broker") or "Tanpa RDN", []).append(p)

    rdns: list[dict[str, Any]] = []
    tot_cash = tot_asset = tot_pl = tot_net_pl = tot_gold_value = tot_gold_pl = tot_gold_cost = 0.0
    for broker in sorted(set(groups) | set(accounts)):
        ps = groups.get(broker, [])
        asset = sum((p.get("value") or 0) for p in ps)                 # nilai pasar (gross)
        net_asset = sum((p.get("net_value") if p.get("net_value") is not None else (p.get("value") or 0)) for p in ps)
        cost = sum((p.get("total_cost") or p.get("cost") or 0) for p in ps)
        pl = sum((p.get("pl") or 0) for p in ps)                       # P/L kotor
        net_pl = sum((p.get("net_pl") if p.get("net_pl") is not None else (p.get("pl") or 0)) for p in ps)
        emiten = len({p["ticker"] for p in ps})
        acc = accounts.get(broker, {})
        cash = float(acc.get("cash") or 0)
        cash_at_broker = acc.get("cash_at_broker")
        cash_at_rdn = acc.get("cash_at_rdn")
        fee_buy = float(acc.get("fee_buy_pct", MM.FEE_BUY_PCT))
        fee_sell = float(acc.get("fee_sell_pct", MM.FEE_SELL_PCT))
        
        # Hitung Nilai Aset Emas
        gold_balance_grams = acc.get("gold_balance_grams")
        gold_avg_price = acc.get("gold_avg_price")
        gold_value = gold_cost = gold_pl = gold_pl_pct = 0.0
        if gold_balance_grams and gold_price_g:
            gold_value = round(gold_balance_grams * gold_price_g)
            if gold_avg_price:
                gold_cost = round(gold_balance_grams * gold_avg_price)
                gold_pl = gold_value - gold_cost
                gold_pl_pct = round(gold_pl / gold_cost * 100, 2) if gold_cost else 0.0
                
        equity = cash + asset + gold_value
        advice = _mm_advice(cash, emiten, target, fee_buy, fee_sell) if broker != "Tring Pegadaian" else None
        cash_pct = round(cash / equity * 100, 1) if equity else None
        cr = round(cash / cost * 100, 2) if (cost and cash is not None) else None
        rdns.append({
            "broker": broker, "rdn": acc.get("rdn"), "bank": acc.get("bank"),
            "account_id": acc.get("id"), "has_cash": broker in accounts,
            "fee_buy_pct": fee_buy, "fee_sell_pct": fee_sell,
            "cash": round(cash), "asset_value": round(asset), "net_asset": round(net_asset),
            "cost": round(cost),
            "pl": round(net_pl), "pl_gross": round(pl),
            "pl_pct": round(net_pl / cost * 100, 2) if cost else None,
            "equity": round(equity),
            "emiten": emiten if broker != "Tring Pegadaian" else 0,
            "target_emiten": target if broker != "Tring Pegadaian" else 0,
            "cash_pct": cash_pct, "asset_pct": round(asset / equity * 100, 1) if equity else None,
            "tickers": sorted({p["ticker"] for p in ps}),
            "advice": advice, "health": _health(cash_pct, advice["open_slots"]) if advice else None,
            "cash_at_broker": round(cash_at_broker) if cash_at_broker is not None else None,
            "cash_at_rdn": round(cash_at_rdn) if cash_at_rdn is not None else None,
            "current_ratio": cr,
            "gold_balance_grams": gold_balance_grams,
            "gold_avg_price": gold_avg_price,
            "gold_value": gold_value if gold_balance_grams else None,
            "gold_cost": gold_cost if gold_balance_grams else None,
            "gold_pl": gold_pl if gold_balance_grams else None,
            "gold_pl_pct": gold_pl_pct if gold_balance_grams else None,
            "gold_pct": round(gold_value / equity * 100, 1) if (equity and gold_balance_grams) else None,
        })
        tot_cash += cash
        tot_asset += asset
        tot_pl += pl
        tot_net_pl += net_pl
        tot_gold_value += gold_value
        tot_gold_pl += gold_pl
        tot_gold_cost += gold_cost

    tot_equity = tot_cash + tot_asset + tot_gold_value
    tot_pl_all = tot_net_pl + tot_gold_pl
    return {
        "rdn": rdns,
        "total": {
            "cash": round(tot_cash), "asset_value": round(tot_asset),
            "gold_value": round(tot_gold_value),
            "equity": round(tot_equity), "pl": round(tot_pl_all), "pl_gross": round(tot_pl),
            "cash_pct": round(tot_cash / tot_equity * 100, 1) if tot_equity else None,
            "asset_pct": round(tot_asset / tot_equity * 100, 1) if tot_equity else None,
            "gold_pct": round(tot_gold_value / tot_equity * 100, 1) if tot_equity else None,
            "target_emiten": target, "jumlah_rdn": len(rdns),
        },
        "catatan": ("Cash & aset dirinci per RDN. Saran alokasi memakai metode Money Management "
                    f"(dana trading {MM.TRADING_FUND_PCT:.0f}% dari cash, sisanya cadangan) dan menjaga "
                    f"jumlah emiten = {target}. Advisory — bukan ajakan beli/jual, tunai non-margin."),
    }
