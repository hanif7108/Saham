#!/usr/bin/env python3
"""
CLI Script to send the Top-5 Watchlist summary to Telegram.
Can be scheduled using system cron.
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from datetime import datetime
from app.core import decisions, telegram_notify, reminders

def main():
    now = datetime.now()
    today = now.date()
    
    # 1. Periksa apakah hari ini hari bursa.
    # Jika bukan hari bursa, keluar secara aman tanpa mengirim notifikasi (mencegah spam)
    if not reminders.is_trading_day(today):
        print(f"[{now.isoformat()}] Hari ini bukan hari bursa. Keluar aman.")
        sys.exit(0)
        
    print(f"[{now.isoformat()}] Memulai pengiriman ringkasan Top-5 Watchlist...")
    
    # 2. Ambil data keputusan (Top-5 dihitung di dalamnya)
    try:
        data = decisions.build_decisions()
    except Exception as e:
        print(f"Gagal menghitung keputusan: {e}")
        sys.exit(1)
        
    top5_detail = data.get("top5_detail", [])
    if not top5_detail:
        print("Daftar Top-5 kosong. Tidak mengirim notifikasi.")
        sys.exit(0)
        
    # 3. Format pesan HTML
    bursa_time = data.get("bursa", {}).get("now_wib", now.strftime("%Y-%m-%d %H:%M WIB"))
    
    message_lines = [
        "<b>☪ SHARIA TRADING AI — TOP-5 WATCHLIST</b>",
        f"📅 <i>{bursa_time}</i>",
        ""
    ]
    
    for i, item in enumerate(top5_detail, 1):
        ticker = item["ticker"]
        sentiment = item.get("status") or "TERTAHAN"
        conv = item["conviction"]
        acc = item.get("akurasi_pct")
        acc_str = f"{acc:.1f}%" if acc is not None else "—"
        
        # Pilihan status emiten (Dimiliki / Beli / Rotasi / Tertahan)
        status_icon = "🟢" if sentiment in ("BUY", "BELI") else "🟡" if sentiment in ("HOLD", "DIMILIKI") else "⚪"
        
        message_lines.append(f"{i}. {status_icon} <b>{ticker}</b> ({sentiment})")
        message_lines.append(f"   • Akurasi Prediksi: {acc_str} · Keyakinan: {conv:.1f}%")
        message_lines.append(f"   • Fundamental: {item['funnel_skor']}/6 · Undervalue: {item['uv_score']}/3")
        
    message_lines.extend([
        "",
        "💡 <i>Status RDN:</i>",
    ])
    
    for r in data.get("rdn", []):
        broker = r.get("broker", "RDN")
        cash = r.get("cash", 0)
        message_lines.append(f"   • {broker}: Rp {cash:,.0f}")
        
    text = "\n".join(message_lines)
    
    # 4. Kirim notifikasi
    res = telegram_notify.send(text)
    if res.get("ok"):
        print(f"Notifikasi berhasil dikirim (Message ID: {res.get('message_id')})")
    else:
        print(f"Gagal mengirim notifikasi: {res.get('error')}")
        sys.exit(1)

if __name__ == "__main__":
    main()
