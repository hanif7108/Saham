"""
Pemantau Funnel intraday — tiap N menit (jam bursa) jalankan Pusat Keputusan,
deteksi sinyal SIGNIFIKAN & BARU, lalu kirim Telegram agar bisa dieksekusi.

Signifikan = aksi yang berdampak ke ROI dan layak dieksekusi sekarang:
  • JUAL mendesak  : cut-loss / take-profit / fundamental AVOID.
  • BELI kuat       : skor keyakinan ≥ ambang & ada alokasi (cash + slot).
  • ROTASI          : tukar emiten lemah → kuat.

Anti-spam: state harian (data_store/watch_state.json) — alert hanya saat sinyal
BARU muncul, tidak diulang tiap 15 menit.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.config import BASE_DIR, settings
from app.core import decisions, telegram_notify

STATE = BASE_DIR.parent / "data_store" / "watch_state.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _save(d: dict) -> None:
    try:
        STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    except Exception:  # noqa: BLE001
        pass


def _rp(n: Any) -> str:
    try:
        return ("Rp " + f"{int(n):,}").replace(",", ".")
    except (TypeError, ValueError):
        return "-"


def _significant(d: dict) -> list[tuple[str, dict]]:
    """Kumpulkan aksi signifikan dari hasil Pusat Keputusan."""
    out: list[tuple[str, dict]] = []
    for x in d.get("sell", []):
        r = x.get("reason", "")
        if (x.get("urgency") == "URGENT" or "CUT LOSS" in r or "TAKE PROFIT" in r
                or "AVOID" in r or x.get("context") == "ROTATION_OUT"):
            out.append(("SELL", x))
    minc = float(settings.funnel_watch_min_conviction)
    for x in d.get("buy", []):
        a = x.get("alokasi") or {}
        strong = (x.get("conviction") or 0) >= minc
        actionable = a.get("tipe") == "beli" and (a.get("lots") or 0) > 0
        if strong and actionable:
            out.append(("BUY", x))
    return out


def _sig(kind: str, x: dict) -> str:
    return f"{kind}:{x.get('ticker')}:{x.get('context', '')}"


def _line(kind: str, x: dict) -> str:
    tk = x.get("ticker")
    if kind == "SELL":
        ep = x.get("exit_plan") or {}
        plan = ""
        if ep.get("lots_now"):
            st1 = (ep.get("stages") or [{}])[0]
            plan = f" → jual {ep['lots_now']}/{ep['lots_total']} lot" + (f" ≈ {_rp(st1.get('nilai_net'))}" if st1.get("nilai_net") else "")
        return f"🔴 <b>{tk}</b> — {x.get('reason', '')[:70]}{plan}"
    
    a = x.get("alokasi") or {}
    alloc = f" → ~{a.get('lots')} lot @ {a.get('rdn')} ≈ {_rp(a.get('outlay_idr'))}" if a.get("lots") else ""
    base_line = f"🟢 <b>{tk}</b> (skor {x.get('conviction')}, akurasi {x.get('akurasi_pct')}%){alloc}"
    
    v = x.get("ai_verdict")
    if v and isinstance(v, dict):
        rec = v.get("rekomendasi_claude") or v.get("rekomendasi")
        keyak = v.get("keyakinan")
        entry = v.get("entry_ideal") or v.get("entry_pre_closing")
        tp = v.get("target_harga") or v.get("target_pre_opening")
        sl = v.get("stop_loss")
        risk = v.get("risiko_utama")
        
        ai_details = f"\n   🧠 <b>Strategy AI:</b> {rec} (Keyakinan: {keyak})"
        plans = []
        if entry: plans.append(f"Entry: {_rp(entry)}")
        if tp: plans.append(f"TP: {_rp(tp)}")
        if sl: plans.append(f"SL: {_rp(sl)}")
        if plans:
            ai_details += f" · " + " · ".join(plans)
        if risk:
            ai_details += f"\n   ⚠️ Risiko: {risk}"
        return f"{base_line}{ai_details}"
        
    return base_line


def check_trailing_stops(d: dict) -> list[str]:
    """Pantau pergerakan harga posisi portofolio yang masuk area TP untuk trailing stop."""
    import math
    from app.core import portfolio
    
    # Ambil trailing stop percentage dari config (default 3.0%)
    trailing_pct = getattr(settings, "trailing_stop_pct", 3.0)
    
    # Ambil TP target dari adaptive strategy
    tp_target = d.get("adaptive", {}).get("take_profit_net_pct", 20.0)
    
    # Load trailing state
    trailing_state_file = BASE_DIR.parent / "data_store" / "trailing_state.json"
    try:
        state = json.loads(trailing_state_file.read_text()) if trailing_state_file.exists() else {}
    except Exception:
        state = {}
        
    portfolio_res = portfolio.list_positions()
    positions = portfolio_res.get("positions", [])
    
    current_keys = set()
    alerts = []
    state_changed = False
    
    for p in positions:
        ticker = p["ticker"]
        broker = p.get("broker") or "Tanpa RDN"
        key = f"{ticker}:{broker}"
        current_keys.add(key)
        
        cur_price = p.get("current_price")
        avg_price = p.get("avg_price")
        lots = p.get("lots", 0)
        
        if cur_price is None or avg_price is None or cur_price <= 0 or avg_price <= 0:
            continue
            
        # P/L kotor/bersih
        pl_pct = p.get("net_pl_pct")
        if pl_pct is None:
            pl_pct = p.get("pl_pct")
        if pl_pct is None:
            pl_pct = ((cur_price - avg_price) / avg_price) * 100
            
        p_state = state.get(key)
        
        # 1. Masuk area TP pertama kali
        if pl_pct >= tp_target:
            if not p_state:
                p_state = {
                    "peak_price": cur_price,
                    "tp_crossed": True,
                    "triggered": False,
                    "activation_date": datetime.now().isoformat()
                }
                state[key] = p_state
                state_changed = True
                
                # Hitung sisa lot untuk Tahap 2 (setengahnya)
                lots_now = min(lots, max(1, math.ceil(lots * 0.5))) if lots else 0
                lots_rest = lots - lots_now
                
                alerts.append(
                    f"🎉 <b>Target TP Terpenuhi: {ticker} ({broker})</b>\n"
                    f"• P/L Bersih: {pl_pct:+.2f}%\n"
                    f"• Harga Beli Rata-rata: {avg_price:.0f}\n"
                    f"• Harga Saat Ini: {cur_price:.0f}\n"
                    f"• Rekomendasi: Eksekusi <b>Tahap 1 (Jual {lots_now} Lot)</b> di harga {cur_price:.0f}.\n"
                    f"• Sisa {lots_rest} Lot masuk mode <b>Trailing Stop</b> (proteksi dari puncak)."
                )
            else:
                # 2. Sedang trailing: update peak_price jika ada harga baru yang lebih tinggi
                if not p_state.get("triggered", False):
                    if cur_price > p_state["peak_price"]:
                        p_state["peak_price"] = cur_price
                        state_changed = True
                    
                    # 3. Cek apakah harga turun dari puncak melewati toleransi trailing
                    peak = p_state["peak_price"]
                    trigger_price = peak * (1 - trailing_pct / 100)
                    if cur_price <= trigger_price:
                        p_state["triggered"] = True
                        state_changed = True
                        
                        lots_now = min(lots, max(1, math.ceil(lots * 0.5))) if lots else 0
                        lots_rest = lots - lots_now
                        # sisa lot yang di-trail
                        to_sell = lots_rest if lots_rest > 0 else lots
                        
                        alerts.append(
                            f"🚨 <b>ALERT TRAILING STOP: {ticker} ({broker})</b>\n"
                            f"• Harga Saat Ini: {cur_price:.0f}\n"
                            f"• Harga Puncak: {peak:.0f}\n"
                            f"• Penurunan dari Puncak: {((peak - cur_price)/peak*100):.2f}% (Toleransi: {trailing_pct}%)\n"
                            f"• Rekomendasi: <b>Jual Sisa {to_sell} Lot</b> segera di aplikasi untuk mengamankan keuntungan."
                        )
                        
    # Bersihkan state untuk posisi yang sudah tidak ada di portofolio
    for key in list(state.keys()):
        if key not in current_keys:
            state.pop(key)
            state_changed = True
            
    if state_changed:
        try:
            trailing_state_file.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        except Exception:
            pass
            
    return alerts


def run_and_alert(force: bool = False) -> dict[str, Any]:
    """Jalankan funnel (via cache/prefetch), kirim Telegram bila sinyal BARU. force=abaikan anti-dobel."""
    from app.core import funnel_cache

    # Pakai/isi cache Pusat Keputusan agar web & Telegram sejalan
    d = funnel_cache.build_fresh() if force else funnel_cache.get_decisions(refresh=False)
    bursa = d.get("bursa") or {}
    items = _significant(d)

    # --- Jalankan Trailing Stop Checks ---
    trailing_alerts = check_trailing_stops(d)
    for alert in trailing_alerts:
        telegram_notify.send(alert)

    now = datetime.now()
    today = now.date().isoformat()
    state = _load()
    if state.get("date") != today:
        state = {"date": today, "alerted": []}
    alerted = set(state.get("alerted", []))

    new = [(k, x) for k, x in items if force or _sig(k, x) not in alerted]
    sent = False
    if new:
        roi = d.get("roi") or {}
        head = f"🔔 <b>Update Trading</b> ({bursa.get('now_wib', now.strftime('%H:%M'))}) — {len(new)} sinyal baru"
        gap = (roi.get("gap_to_target"))
        sub = f"ROI integral {roi.get('integral', {}).get('roi_pct')}% (gap {gap}pp ke 6%)" if roi else ""
        body = "\n".join(_line(k, x) for k, x in new)
        tail = "\nEksekusi di app (Portofolio/Jual atau order broker). Cut-loss −7% wajib · ambil profit ≥ +6,4% net."
        telegram_notify.send("\n".join(filter(None, [head, sub, "", body, tail])))
        sent = True
        for k, x in new:
            alerted.add(_sig(k, x))
        state["alerted"] = sorted(alerted)
    state["last_run"] = now.isoformat(timespec="seconds")
    _save(state)
    return {"ok": True, "significant": len(items), "new": len(new), "sent": sent,
            "bursa": {"session": bursa.get("session"), "open": bursa.get("open")},
            "items": [{"action": k, "ticker": x.get("ticker"), "reason": x.get("reason", "")[:80]} for k, x in items]}
