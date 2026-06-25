from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os

from app.core.learning import LearningManager

router = APIRouter(prefix="/api/learning", tags=["learning"])

class ProgressUpdateRequest(BaseModel):
    completed: bool

@router.get("/modules")
def get_modules(force_rescan: bool = False):
    """Mengambil daftar modul kurikulum, file template pendukung, dan progress belajar user."""
    try:
        modules = LearningManager.get_modules_data(force_rescan=force_rescan)
        resources = LearningManager.get_resources_data()
        progress = LearningManager.get_progress()
        
        # Hitung progress awal
        active_modules = [m for m in modules if m["exists"]]
        total = len(active_modules)
        completed_count = sum(1 for m in active_modules if progress.get(m["id"], False))
        pct = round(completed_count / total * 100) if total > 0 else 0
        
        return {
            "modules": modules,
            "resources": resources,
            "progress": progress,
            "pct": pct,
            "completed_count": completed_count,
            "total_count": total
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memuat kurikulum: {str(e)}")

@router.get("/pdf/{module_id}")
def stream_pdf(module_id: str):
    """Mengalirkan file PDF kurikulum untuk dibaca di penampil iframe."""
    path = LearningManager.get_file_response_path(module_id, is_resource=False)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Modul PDF tidak ditemukan.")
    
    filename = os.path.basename(path)
    # Gunakan inline agar browser merender PDF di dalam iframe alih-alih mengunduhnya
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=filename,
        headers={"Content-Disposition": f"inline; filename=\"{filename}\""}
    )

@router.get("/download/{resource_id}")
def download_resource(resource_id: str):
    """Mengunduh file Excel (.xlsx) atau ZIP sumber daya belajar."""
    path = LearningManager.get_file_response_path(resource_id, is_resource=True)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Sumber daya tidak ditemukan.")
    
    filename = os.path.basename(path)
    # Gunakan attachment agar browser langsung mengunduh file
    return FileResponse(
        path,
        media_type="application/octet-stream",
        filename=filename,
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""}
    )

@router.post("/progress/{module_id}")
def update_progress(module_id: str, payload: ProgressUpdateRequest):
    """Menyimpan progress selesai/belum suatu modul belajar."""
    try:
        res = LearningManager.update_progress(module_id, payload.completed)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal memperbarui progress: {str(e)}")
