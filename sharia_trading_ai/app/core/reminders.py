"""
Pengingat harian via Telegram — menjaga "loop harian" trading tak terlewat.

  • PAGI (sebelum bursa buka)  → "Siapkan Order" + rencana hari ini.
  • SORE (sesudah bursa tutup) → "Jalankan Funnel & Review" + rencana besok.

Hanya pada hari bursa (lewati akhir pekan & libur BEI). Isi pesan = ringkasan
Pusat Keputusan (BELI/JUAL keyakinan tinggi + alokasi MM) + ROI + disiplin.
Dijadwalkan oleh loop startup di app/main.py.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.core import bei_calendar, decisions, telegram_notify


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and not bei_calendar.is_holiday(d)


def _rp(n: Any) -> str:
    try:
        return ("Rp " + f"{int(n):,}").replace(",", ".")
    except (TypeError, ValueError):
        return "-"


def build_plan_text(kind: str) -> str:
    """Susun pesan pengingat (HTML Telegram) dgn ringkasan rencana trading."""
    now = datetime.now()
    # force_open → sinyal penuh utk perencanaan (walau bursa tutup saat pengingat)
    d = decisions.build_decisions(force_open=True)
    r = d.get("roi") or {}
    integral = (r.get("integral") or {}).get("roi_pct")
    gap = r.get("gap_to_target")
    buys = (d.get("buy") or [])[:3]
    sells = [s for s in (d.get("sell") or [])
             if "CUT LOSS" in s.get("reason", "") or s.get("urgency") == "URGENT"][:3]
    bz = d.get("bursa") or {}
    ad = d.get("adaptive") or {}

    if kind == "morning":
        head = "🌅 <b>Pagi — Siapkan Order</b>"
        sub = "Bursa buka 09:00. Jangan FOMO di pembukaan; tunggu 09:15–09:30. Pasang limit order sesuai rencana."
    else:
        head = "🌆 <b>Sore — Jalankan Funnel &amp; Review</b>"
        sub = "Bursa tutup. Catat penjualan via tombol 💰 Jual, lalu siapkan rencana sesi berikutnya."

    lines = [f"{head}  <i>({now:%a %d %b %Y})</i>", sub]
    if integral is not None:
        lines.append(f"🎯 ROI integral <b>{integral}%</b> (gap {gap}pp menuju 6%)"
                     + (f" · ambang akurasi BELI {ad.get('min_buy_accuracy')}%" if ad.get("min_buy_accuracy") else ""))

    if buys:
        lines.append("\n🟢 <b>BELI — keyakinan tertinggi:</b>")
        for b in buys:
            a = b.get("alokasi") or {}
            cv = b.get("conviction")
            if a.get("lots"):
                alloc = f"~{a['lots']} lot @ {a.get('rdn')} ≈ {_rp(a.get('outlay_idr') or a.get('nilai_idr'))}"
                tgt = f" · jual +{a.get('net_target_pct')}% net" if a.get("net_target_pct") else ""
            else:
                alloc = a.get("catatan") or "lihat app"
                tgt = ""
            meta = (f"skor {cv}, " if cv is not None else "") + f"akurasi {b.get('akurasi_pct')}%"
            lines.append(f" • <b>{b['ticker']}</b> ({meta}) — {alloc}{tgt}")
    else:
        lines.append("\n🟢 Tidak ada BELI berkeyakinan tinggi → tahan cash, jangan paksa.")

    if sells:
        lines.append("\n🔴 <b>JUAL / CUT-LOSS:</b>")
        for s in sells:
            lines.append(f" • <b>{s['ticker']}</b> — {s.get('reason', '')[:80]}")

    lines.append("\n📏 <b>Disiplin:</b> cut-loss −7% wajib · jual untung ≥ +6,4% net · maks 3 emiten/RDN · biarkan profit berjalan.")
    nx = bz.get("next_holiday")
    if nx:
        lines.append(f"📅 Libur bursa berikutnya: {nx['name']} ({nx['date']}).")
    lines.append("\n<i>Advisory — keputusan &amp; risiko sepenuhnya di tangan Anda.</i>")
    return "\n".join(lines)


def send_reminder(kind: str) -> dict[str, Any]:
    """Susun & kirim pengingat. Bila ringkasan gagal, tetap kirim teks pengingat dasar."""
    try:
        text = build_plan_text(kind)
    except Exception as e:  # noqa: BLE001
        base = ("🌅 Pagi — siapkan order & ikuti rencana app." if kind == "morning"
                else "🌆 Sore — Jalankan Funnel & review portofolio.")
        text = f"{base}\n(ringkasan otomatis gagal: {e})"
    return telegram_notify.send(text)
