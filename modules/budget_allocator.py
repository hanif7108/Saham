"""
Budget Allocator — Priority-Based Daily Trading Budget
======================================================
Mengalokasikan budget harian untuk rekomendasi BUY (saham IDX, saham US,
emas, perak, dinar) berdasarkan **prioritas paling menguntungkan**, dengan
batas keras: total alokasi rupiah ≤ total aset yang dimiliki saat ini.

Filosofi
--------
Sebelumnya dashboard membagi rata `trading_fund_rp / n_buy` ke setiap
ticker BUY tanpa mempertimbangkan kualitas sinyal, dan komoditas (emas,
perak, dinar) dialokasikan terpisah hanya berbasis gap_rp dari rebalancer.
Akibatnya, total rekomendasi BUY harian bisa melebihi kas aktual user.

Modul ini menyeragamkan semua kandidat BUY ke satu format `Candidate`,
menghitung composite priority score:

    composite = urgency_w × confidence_w × max(1.0, expected_return_pct)

lalu **greedy-allocate** dari skor tertinggi ke terendah. Saat sisa budget
sudah tidak cukup untuk requested_amount item berikutnya, item tersebut
ditandai `status="DEFERRED"` dengan alasan "budget habis".

Output Candidate diperkaya dengan:
  - composite_score, rank
  - status: "ALLOCATED" | "DEFERRED" | "ALLOCATED_PARTIAL"
  - allocated_amount_rp, allocated_lot / allocated_gram
  - defer_reason (kalau DEFERRED)

Konstrak budget
---------------
Diserahkan ke caller. Pilihan yang user sudah konfirmasi:
  cap = total_asset_rp (saham + emas + cash) — paling agresif, asumsi user
  mau rotasi antar bucket. Caller bertanggung jawab pass nilai yang benar.

Catatan: modul ini TIDAK memutuskan apakah user harus SELL untuk
membebaskan dana — hanya menjamin sum(allocated) ≤ budget_cap. Logika
SELL-first tetap di decision.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ---------- Bobot ranking ---------- #
URGENCY_WEIGHT = {"URGENT": 4.0, "HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}
CONFIDENCE_WEIGHT = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}

# Floor untuk expected_return supaya item tanpa ekspektasi cuan tidak nol-out
EXPECTED_RETURN_FLOOR = 1.0  # %

# Asset-class tie-breaker (bila composite sama persis)
ASSET_CLASS_PRIORITY = {
    "saham_idx": 5,   # paling likuid & paling cepat compounding
    "saham_us":  4,
    "emas":      3,
    "perak":     2,
    "dinar":     1,
}


@dataclass
class Candidate:
    """Satu kandidat BUY untuk dialokasikan budget."""
    id: str                       # ticker (saham) atau nama item (e.g. "Emas 10g")
    asset_class: str              # saham_idx | saham_us | emas | perak | dinar
    urgency: str                  # URGENT | HIGH | MEDIUM | LOW
    confidence: str               # HIGH | MEDIUM | LOW
    expected_return_pct: float    # ekspektasi cuan (%) — default 0
    requested_amount_rp: float    # Rp yang diminta sizing original
    price: float = 0.0            # harga per unit (Rp/lembar utk saham, Rp/gram utk emas)
    lot_or_gram: float = 0.0      # ukuran unit (lot utk saham, gram utk komoditas)
    reason: str = ""              # alasan rekomendasi (carried-over dari decision.py)
    meta: Dict[str, Any] = field(default_factory=dict)

    # Diisi oleh allocator
    composite_score: float = 0.0
    rank: int = 0
    status: str = "PENDING"            # ALLOCATED | ALLOCATED_PARTIAL | DEFERRED
    allocated_amount_rp: float = 0.0
    allocated_lot_or_gram: float = 0.0
    defer_reason: str = ""

    def compute_score(self) -> float:
        u = URGENCY_WEIGHT.get(self.urgency, 1.0)
        c = CONFIDENCE_WEIGHT.get(self.confidence, 1.0)
        r = max(EXPECTED_RETURN_FLOOR, float(self.expected_return_pct or 0))
        self.composite_score = round(u * c * r, 3)
        return self.composite_score


def _tie_breaker(c: Candidate):
    """Sort key (descending). Composite tinggi → atas; tie pakai asset_class lalu return%."""
    return (
        c.composite_score,
        ASSET_CLASS_PRIORITY.get(c.asset_class, 0),
        c.expected_return_pct,
    )


def allocate_budget(
    candidates: List[Candidate],
    budget_cap_rp: float,
    allow_partial: bool = False,
    min_alloc_rp: float = 0.0,
) -> Dict[str, Any]:
    """
    Greedy allocate budget ke kandidat berdasarkan composite score.

    Args:
        candidates: list kandidat BUY (sudah include sizing requested_amount_rp).
        budget_cap_rp: total budget yang boleh dipakai hari ini.
                       Caller pilih: total_asset_rp / cash_only / cash + gap.
        allow_partial: bila True, item yang sebagian muat akan dialokasikan
                       partial (saham di-floor ke kelipatan lot, komoditas
                       di-floor ke 0.01 gram). Bila False (default — sesuai
                       preferensi user "DEFERRED"), item all-or-nothing.
        min_alloc_rp: alokasi minimum supaya partial allocation tidak terlalu
                      kecil (e.g. < 100rb tidak worth).

    Returns:
        {
          "budget_cap_rp":  float,
          "used_rp":        float,  # sum allocated
          "remaining_rp":   float,
          "n_allocated":    int,
          "n_deferred":     int,
          "candidates":     List[Candidate] (sudah diisi score/status/rank),
          "by_class_rp":    {asset_class: allocated_rp}
        }
    """
    if budget_cap_rp is None or budget_cap_rp < 0:
        budget_cap_rp = 0.0

    # 1. Reset state (supaya idempotent saat di-panggil ulang) + skoring & sorting
    for c in candidates:
        c.status = "PENDING"
        c.allocated_amount_rp = 0.0
        c.allocated_lot_or_gram = 0.0
        c.defer_reason = ""
        c.compute_score()
    sorted_cands = sorted(candidates, key=_tie_breaker, reverse=True)
    for idx, c in enumerate(sorted_cands, start=1):
        c.rank = idx

    # 2. Greedy allocate
    remaining = float(budget_cap_rp)
    by_class: Dict[str, float] = {}

    for c in sorted_cands:
        req = max(0.0, float(c.requested_amount_rp or 0))
        if req <= 0:
            c.status = "DEFERRED"
            c.defer_reason = "Sizing 0 (harga/budget unit tidak tersedia)"
            continue

        if req <= remaining:
            # Cukup → alokasikan penuh
            c.status = "ALLOCATED"
            c.allocated_amount_rp = round(req, 0)
            c.allocated_lot_or_gram = c.lot_or_gram
            remaining -= req
            by_class[c.asset_class] = by_class.get(c.asset_class, 0.0) + req
        else:
            # Tidak cukup → coba partial kalau diizinkan
            if allow_partial and remaining >= max(min_alloc_rp, c.price * _unit_step(c.asset_class)):
                # Hitung berapa unit yang muat
                price = max(1.0, float(c.price))
                step = _unit_step(c.asset_class)  # 1 lot (=100 lembar) atau 0.01 gram
                unit_cost = price * step
                if unit_cost <= 0:
                    c.status = "DEFERRED"
                    c.defer_reason = "Harga unit tidak valid untuk partial"
                    continue
                max_units = int(remaining // unit_cost)
                if max_units <= 0:
                    c.status = "DEFERRED"
                    c.defer_reason = (
                        f"Sisa budget Rp{remaining:,.0f} < harga 1 "
                        f"{_unit_label(c.asset_class)} (Rp{unit_cost:,.0f})"
                    )
                    continue
                alloc_amt = max_units * unit_cost
                if alloc_amt < min_alloc_rp:
                    c.status = "DEFERRED"
                    c.defer_reason = (
                        f"Partial Rp{alloc_amt:,.0f} < minimum Rp{min_alloc_rp:,.0f}"
                    )
                    continue
                c.status = "ALLOCATED_PARTIAL"
                c.allocated_amount_rp = round(alloc_amt, 0)
                c.allocated_lot_or_gram = round(max_units * step, 4)
                remaining -= alloc_amt
                by_class[c.asset_class] = by_class.get(c.asset_class, 0.0) + alloc_amt
            else:
                c.status = "DEFERRED"
                c.defer_reason = (
                    f"Budget habis — butuh Rp{req:,.0f}, sisa hanya "
                    f"Rp{remaining:,.0f}"
                )

    used = float(budget_cap_rp) - remaining
    n_alloc = sum(1 for c in sorted_cands if c.status.startswith("ALLOCATED"))
    n_def = sum(1 for c in sorted_cands if c.status == "DEFERRED")

    return {
        "budget_cap_rp":  round(float(budget_cap_rp), 0),
        "used_rp":        round(used, 0),
        "remaining_rp":   round(remaining, 0),
        "utilization_pct": round((used / budget_cap_rp * 100) if budget_cap_rp > 0 else 0.0, 2),
        "n_candidates":   len(sorted_cands),
        "n_allocated":    n_alloc,
        "n_deferred":     n_def,
        "candidates":     sorted_cands,
        "by_class_rp":    {k: round(v, 0) for k, v in by_class.items()},
    }


def _unit_step(asset_class: str) -> float:
    """Step terkecil pembelian per asset class."""
    if asset_class in ("saham_idx", "saham_us"):
        return 100.0   # 1 lot = 100 lembar (IDX). US tidak ada lot tapi pakai 1 share = unit terkecil; treat 100 utk normalisasi
    if asset_class in ("emas", "perak"):
        return 0.01    # 0.01 gram (Pegadaian min)
    if asset_class == "dinar":
        return 1.0     # 1 koin
    return 1.0


def _unit_label(asset_class: str) -> str:
    if asset_class in ("saham_idx", "saham_us"):
        return "lot"
    if asset_class in ("emas", "perak"):
        return "gram"
    if asset_class == "dinar":
        return "koin"
    return "unit"


def candidates_to_dict(cands: List[Candidate]) -> List[Dict[str, Any]]:
    """Konversi list Candidate ke list dict (untuk JSON response)."""
    return [asdict(c) for c in cands]


# ---------- Helper konstruktor: dari decision/dashboard output ---------- #

def from_buy_decision(
    decision: Dict[str, Any],
    sizing: Dict[str, Any],
    asset_class: str = "saham_idx",
    expected_return_pct: Optional[float] = None,
) -> Candidate:
    """
    Bangun Candidate dari output `decide_for_*` (decision.py) +
    sizing dict yang dihitung dashboard (price, lot, amount_rp, ob1/ob2/ob3).
    """
    if expected_return_pct is None:
        # Coba ambil dari decision.details (jalur7 / step_info / target_profit)
        details = decision.get("details") or {}
        expected_return_pct = float(
            details.get("expected_return_pct")
            or details.get("target_profit_pct")
            or 0.0
        )
    return Candidate(
        id=str(decision.get("ticker", "")).upper(),
        asset_class=asset_class,
        urgency=decision.get("urgency", "LOW"),
        confidence=decision.get("confidence", "LOW"),
        expected_return_pct=float(expected_return_pct or 0.0),
        requested_amount_rp=float(sizing.get("amount_rp") or 0.0),
        price=float(sizing.get("price") or 0.0),
        lot_or_gram=float(sizing.get("lot") or 0.0),
        reason=str(decision.get("reason", "")),
        meta={
            "context": decision.get("context", ""),
            "next_step": decision.get("next_step", ""),
            "details": decision.get("details", {}),
            "sizing": sizing,
        },
    )


def from_commodity(
    name: str,
    asset_class: str,
    price_per_unit: float,
    requested_gram_or_count: float,
    expected_return_pct: float,
    urgency: str = "MEDIUM",
    confidence: str = "MEDIUM",
    reason: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> Candidate:
    """Bangun Candidate untuk komoditas (emas/perak/dinar)."""
    requested_amount = max(0.0, price_per_unit * requested_gram_or_count)
    return Candidate(
        id=name,
        asset_class=asset_class,
        urgency=urgency,
        confidence=confidence,
        expected_return_pct=float(expected_return_pct or 0.0),
        requested_amount_rp=requested_amount,
        price=float(price_per_unit or 0.0),
        lot_or_gram=float(requested_gram_or_count or 0.0),
        reason=reason,
        meta=meta or {},
    )
