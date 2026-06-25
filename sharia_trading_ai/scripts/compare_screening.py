"""
Bandingkan kualitas screening 6 Magic Number: master_data CSV (lama) vs TradingView (live).

READ-ONLY — tidak mengubah funnel/app. Menampilkan saham yang BERUBAH verdict
fundamental antara kedua sumber, supaya peningkatan akurasi (false positive yang
hilang / peluang yang sebelumnya terlewat) terlihat konkret sebelum integrasi.

Jalankan dari folder sharia_trading_ai:
    python3 -m scripts.compare_screening            # seluruh universe
    python3 -m scripts.compare_screening BBCA ANTM  # ticker tertentu
"""

from __future__ import annotations

import sys

from app.config import FUND
from app.core import fundamental
from app.data import master_data, tradingview_provider


def _label(full: int, full_eval: int) -> str:
    if full_eval == 0:
        return "NO DATA"
    if full >= 6:
        return "STRONG BUY"
    if full >= 4:
        return "BUY"
    if full >= 2:
        return "HOLD"
    return "AVOID"


def _score_from_metrics(m: dict) -> tuple[int, int, str]:
    """6 Magic score + label dari satu set metrik (logika identik fundamental.py)."""
    eps, roa, roe = m.get("eps_growth"), m.get("roa"), m.get("roe")
    der, pbv, per, dy = m.get("der"), m.get("pbv"), m.get("per"), m.get("dy")
    bvps, mp = m.get("bvps"), m.get("mp")

    checks = [
        eps is not None and eps >= fundamental.EPS_GROWTH_MIN,
        roa is not None and roa > FUND.ROA_MIN,
        roe is not None and roe > FUND.ROE_MIN,
        der is not None and der < FUND.DER_MAX,
        pbv is not None and pbv < FUND.PBV_MAX,
        per is not None and per < FUND.PER_MAX,
    ]
    evaluated = sum(1 for v in (eps, roa, roe, der, pbv, per) if v is not None)
    score = sum(1 for c in checks if c)

    intrinsic = (bvps is not None and mp is not None and mp > 0 and bvps > mp)
    bonus = dy is not None and dy > FUND.DIVIDEND_YIELD_MIN
    full = score + (1 if bonus else 0) + (1 if intrinsic else 0)
    full_eval = evaluated + (1 if dy is not None else 0) + (1 if (bvps is not None and mp) else 0)
    return score, evaluated, _label(full, full_eval)


def _md_metrics(ticker: str):
    md = master_data.metrics(ticker)
    if not md:
        return None
    return {
        "eps_growth": md["eps_growth"], "roa": md["roa"], "roe": md["roe"],
        "der": (md["der"] / 100) if md["der"] is not None else None,  # % -> rasio
        "pbv": md["pbv"], "per": md["per"], "dy": md["dividend_yield"],
        "bvps": md["bvps"], "mp": md["market_price"],
    }


def main(argv: list[str]) -> int:
    tickers = [t.upper() for t in argv[1:]] or master_data.tickers()
    print(f"Membandingkan {len(tickers)} saham: master_data CSV  vs  TradingView live\n")

    tv = tradingview_provider.scan_fundamentals(tickers)
    if not tv:
        print("⚠️  Gagal mengambil data TradingView (cek koneksi). Batal.")
        return 1

    changed, only_md, only_tv, agree = [], 0, 0, 0
    rows = []
    for t in tickers:
        md_m = _md_metrics(t)
        tv_m = tv.get(t)
        md_lbl = _score_from_metrics(md_m)[2] if md_m else "—"
        tv_res = _score_from_metrics(tv_m) if tv_m else None
        tv_lbl = tv_res[2] if tv_res else "—"
        rec = tv_m.get("recommend_label") if tv_m else "—"

        if md_lbl == tv_lbl:
            agree += 1
        else:
            changed.append((t, md_lbl, tv_lbl, rec, md_m, tv_m))

    # Ringkasan perubahan verdict
    print(f"{'TICKER':8} {'CSV lama':12} {'TradingView':12} {'TV teknikal':12}")
    print("-" * 48)
    for t, md_lbl, tv_lbl, rec, md_m, tv_m in changed:
        flag = ""
        # false positive yang dikoreksi: lama BUY+, TV turun jadi HOLD/AVOID
        if md_lbl in ("STRONG BUY", "BUY") and tv_lbl in ("HOLD", "AVOID", "NO DATA"):
            flag = "  ⚠️  potensi FALSE POSITIVE dikoreksi"
        elif tv_lbl in ("STRONG BUY", "BUY") and md_lbl in ("HOLD", "AVOID", "—"):
            flag = "  ✨ peluang baru (sebelumnya terlewat)"
        print(f"{t:8} {md_lbl:12} {tv_lbl:12} {rec:12}{flag}")

    print("-" * 48)
    print(f"Sama: {agree}   Berubah: {len(changed)}   Total: {len(tickers)}")
    print("\nCatatan: ini perbandingan READ-ONLY. Funnel/app belum diubah.")

    # Contoh detail metrik untuk 3 perubahan pertama (transparansi angka)
    if changed:
        print("\n=== Detail metrik (3 perubahan pertama) ===")
        for t, md_lbl, tv_lbl, rec, md_m, tv_m in changed[:3]:
            print(f"\n[{t}]  CSV={md_lbl}  ->  TV={tv_lbl}")
            keys = ["eps_growth", "roa", "roe", "der", "pbv", "per", "dy"]
            print(f"  {'metrik':10} {'CSV':>10} {'TradingView':>12}")
            for k in keys:
                a = md_m.get(k) if md_m else None
                b = tv_m.get(k) if tv_m else None
                print(f"  {k:10} {str(a):>10} {str(b):>12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
