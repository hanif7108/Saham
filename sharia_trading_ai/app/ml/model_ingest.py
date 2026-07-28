"""
Jalur balik model: NAS models/candidate/ -> validasi -> promosi di Mac Mini.

Alur "pabrik model" (RTX 4090 di kantor, satu LAN dengan NAS):
  1. Mesin training menaruh kandidat di NAS: models/candidate/<nama>/
     berisi artifact LightGBM (.txt) + <artifact>.meta.json + file marker
     PROMOTE (tanda eksplisit "siap dipakai produksi").
  2. Mac Mini (job harian datalake_sync) menarik folder kandidat, lalu
     modul ini MEMVALIDASI setiap kandidat:
       - meta.json valid & feature_columns == kontrak fitur saat ini
       - artifact termuat oleh LightGBM & bisa memprediksi baris dummy
       - meta memuat walkforward_metrics (bukti dievaluasi di rig)
       - ada marker PROMOTE (tanpa itu: kandidat dicatat, tidak dipasang)
  3. Lolos semua -> artifact lama di-backup, kandidat disalin ke
     app/ml/artifacts/ -> auto-reload mtime memuatnya TANPA restart.

Keamanan: validasi gagal = kandidat diabaikan (produksi tidak tersentuh).

CLI:
    python -m app.ml.model_ingest            # proses ml_data/candidate_models/
    python -m app.ml.model_ingest --dry-run  # validasi saja, tanpa promosi
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from app.config import BASE_DIR
from app.ml.data_fetch import ML_DATA_DIR

CANDIDATE_DIR = ML_DATA_DIR / "candidate_models"
ARTIFACT_DIR = BASE_DIR / "ml" / "artifacts"
WIB = ZoneInfo("Asia/Jakarta")

# Nama artifact yang boleh dipromosikan (kontrak produksi)
ALLOWED_PREFIXES = ("ml_signal_h", "ml_rank_h")


def _expected_features(meta: dict) -> list[str] | None:
    from app.ml.features import FEATURE_COLUMNS, RANK_MODEL_FEATURES
    if meta.get("kind") == "rank":
        return RANK_MODEL_FEATURES
    return FEATURE_COLUMNS


def validate_candidate(cdir: Path) -> dict:
    """Validasi satu folder kandidat. Return {ok, reason, files...}."""
    res = {"dir": cdir.name, "ok": False, "promoted": False}
    metas = sorted(cdir.glob("*.meta.json"))
    if not metas:
        return {**res, "reason": "tidak ada *.meta.json"}
    meta_path = metas[0]
    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        return {**res, "reason": f"meta rusak: {e}"}

    model_file = meta.get("model_file") or ""
    if not model_file.startswith(ALLOWED_PREFIXES):
        return {**res, "reason": f"nama artifact di luar kontrak: {model_file}"}
    model_path = cdir / model_file
    if not model_path.exists():
        return {**res, "reason": f"file model hilang: {model_file}"}

    if not meta.get("walkforward_metrics"):
        return {**res, "reason": "meta tanpa walkforward_metrics (belum dievaluasi)"}

    feats = meta.get("feature_columns") or []
    expected = _expected_features(meta)
    if expected is not None and list(feats) != list(expected):
        return {**res, "reason": "feature_columns tidak cocok kontrak fitur saat ini"}

    try:
        import lightgbm as lgb
        booster = lgb.Booster(model_file=str(model_path))
        import pandas as pd
        dummy = pd.DataFrame([np.zeros(len(feats))], columns=feats)
        booster.predict(dummy)
    except Exception as e:
        return {**res, "reason": f"artifact gagal dimuat/prediksi: {e}"}

    res.update(ok=True, reason="valid", meta_file=meta_path.name,
               model_file=model_file,
               has_promote=(cdir / "PROMOTE").exists())
    return res


def promote(cdir: Path, val: dict) -> dict:
    """Backup artifact lama lalu pasang kandidat ke ARTIFACT_DIR."""
    stamp = datetime.now(WIB).strftime("%Y%m%d_%H%M")
    backup = ARTIFACT_DIR / f"backup_{stamp}"
    moved = []
    for fname in (val["model_file"], val["meta_file"]):
        live = ARTIFACT_DIR / fname
        if live.exists():
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(live, backup / fname)
        shutil.copy2(cdir / fname, live)
        moved.append(fname)
    return {"promoted_files": moved, "backup": backup.name if backup.exists() else None}


def run(dry_run: bool = False) -> dict:
    """Proses semua kandidat di CANDIDATE_DIR."""
    results = []
    if not CANDIDATE_DIR.exists():
        return {"candidates": 0, "results": results}
    for cdir in sorted(p for p in CANDIDATE_DIR.iterdir() if p.is_dir()):
        val = validate_candidate(cdir)
        if val["ok"] and val.get("has_promote") and not dry_run:
            try:
                val.update(promote(cdir, val))
                val["promoted"] = True
                # tandai selesai agar tidak dipromosikan berulang
                (cdir / "PROMOTED_AT").write_text(
                    datetime.now(WIB).isoformat(timespec="seconds"))
                (cdir / "PROMOTE").unlink(missing_ok=True)
            except Exception as e:
                val.update(ok=False, reason=f"promosi gagal: {e}")
        results.append(val)
    out = {"candidates": len(results), "results": results,
           "ran_at": datetime.now(WIB).isoformat(timespec="seconds")}
    (ML_DATA_DIR / "model_ingest_last.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(json.dumps(run(dry_run=args.dry_run), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
