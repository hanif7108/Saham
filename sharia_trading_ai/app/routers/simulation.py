"""Endpoint Simulasi Eksekusi Harian (paper trading + learning akurasi prediksi)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core import simulation

router = APIRouter(prefix="/api/simulation", tags=["simulation"])


@router.get("")
def get_simulation():
    """Ringkasan lengkap: posisi simulasi OPEN (P/L berjalan), CLOSED (ROI),
    statistik (win-rate, avg ROI, equity curve) + insight learning."""
    s = simulation.stats()
    s["learning"] = simulation.learning()
    return s


@router.post("/run")
def run_capture(force: bool = False):
    """Rekam rekomendasi BUY Pusat Keputusan HARI INI sebagai simulasi.

    Otomatis dedup (1x/hari, per ticker OPEN). `force=true` melewati dedup
    harian & cek hari bursa (untuk pengujian).
    """
    return simulation.capture_today(force=force)


@router.post("/evaluate")
def run_evaluate():
    """Evaluasi semua posisi simulasi OPEN: tutup bila Target / Stop Loss /
    horizon hari bursa terlampaui."""
    return simulation.evaluate_open()


@router.delete("/{sim_id}")
def delete_simulation(sim_id: int):
    if not simulation.delete(sim_id):
        raise HTTPException(status_code=404, detail="id simulasi tidak ditemukan")
    return {"ok": True, "deleted": sim_id}
