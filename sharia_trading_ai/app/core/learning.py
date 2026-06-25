import os
import json
from typing import Any, Dict, List, Optional
import pdfplumber

TRADER_SAKTI_PATH = "/Users/hanif/Saham/PDS Trader Sakti/Trader Sakti Complete"
AI_SCANNER_PATH = "/Users/hanif/Saham/AI Scanner"
PROGRESS_FILE = "data_store/learning_progress.json"
CACHE_FILE = "data_store/learning_modules_cache.json"

# Definisikan silabus kurikulum pembelajaran secara rapi dan komprehensif
MODULES_METADATA = [
    {
        "id": "ts-m1",
        "filename": "Modul 1 – “Capek Trading Tapi Duit Nggak Nambah Saatnya Balikin Arah Hidup Lo!”.pdf",
        "title": "Modul 1: Capek Trading Tapi Duit Nggak Nambah? Balikin Arah Hidup Lo!",
        "category": "dasar",
        "description": "Memahami kesalahan psikologis dasar mengapa trader pemula sering terjebak dalam siklus lelah tanpa profit nyata.",
        "folder": "trader_sakti",
        "order": 1
    },
    {
        "id": "ts-m4",
        "filename": "Modul 4 Kenapa 90_ Trader Nyangkut.docx.pdf",
        "title": "Modul 4: Kenapa 90% Trader Nyangkut di Pasar?",
        "category": "dasar",
        "description": "Membongkar alasan utama psikologi kegagalan cut loss dan cara menghindari jebakan harga di puncak.",
        "folder": "trader_sakti",
        "order": 2
    },
    {
        "id": "ts-m10",
        "filename": "Modul 10 – Mau Hidup Lo Naik Kelas. Duduk 1 Jam Bareng Modul Ini, Jalan Jadi\xa0Sultan\xa0Kebuka.pdf",
        "title": "Modul 10: Peta Jalan Menuju Trader Konsisten (Sultan)",
        "category": "dasar",
        "description": "Evaluasi akhir dan langkah konkret menaikkan kelas kehidupan finansial Anda melalui kedisiplinan trading.",
        "folder": "trader_sakti",
        "order": 3
    },
    {
        "id": "ts-m2",
        "filename": "Modul 2 – “Sekali Entry, Cuan Puluhan Juta — Rahasia Candlestick Sakti yang Jarang Diajarkan”.pdf",
        "title": "Modul 2: Rahasia Candlestick Sakti & Konfirmasi Entry",
        "category": "teknikal",
        "description": "Membaca bahasa lilin/candlestick untuk menangkap peluang pembalikan arah dengan probabilitas tinggi.",
        "folder": "trader_sakti",
        "order": 4
    },
    {
        "id": "ts-m3",
        "filename": "Modul 3 – “Indikator Cuma Jadi Pajangan Ubah Jadi Mesin Cetak Duit Rp100 Juta per Bulan”.pdf",
        "title": "Modul 3: Mengubah Indikator Menjadi Mesin Cetak Cuan",
        "category": "teknikal",
        "description": "Memaksimalkan indikator teknikal utama (MA, Stochastic, RSI) agar tidak sekadar menjadi hiasan grafik.",
        "folder": "trader_sakti",
        "order": 5
    },
    {
        "id": "ts-golden-map",
        "filename": "Golden Entry Map 9 Titik Masuk Cuan Tanpa Nyangkut.pdf",
        "title": "Golden Entry Map: 9 Titik Masuk Cuan Tanpa Nyangkut",
        "category": "teknikal",
        "description": "Peta panduan visual area support dan pola konfirmasi terbaik untuk melakukan pembelian saham.",
        "folder": "trader_sakti",
        "order": 6
    },
    {
        "id": "ts-night-entry",
        "filename": "PANDUAN RAHASIA ENTRY MALAM HARI 5 Strategi Diam-diam Para Big Player.pdf",
        "title": "Entry Malam Hari: 5 Strategi Big Player",
        "category": "teknikal",
        "description": "Cara trading di malam hari memanfaatkan pola transaksi dan akumulasi institusi besar.",
        "folder": "trader_sakti",
        "order": 7
    },
    {
        "id": "ts-m7",
        "filename": "Modul 7 Lo Salah Besar Kalau Trading Tanpa Proteksi Sakti Ini!.pdf",
        "title": "Modul 7: Proteksi Sakti Modal Trading Anda",
        "category": "risk_management",
        "description": "Menerapkan sistem pengaman otomatis dan stop-loss ketat demi menjaga keberlanjutan modal.",
        "folder": "trader_sakti",
        "order": 8
    },
    {
        "id": "ts-m6",
        "filename": "Modul 6 Modal Receh, Profit Gede.pdf",
        "title": "Modul 6: Mengelola Modal Receh untuk Hasil Maksimal",
        "category": "risk_management",
        "description": "Strategi alokasi dana kecil agar bisa bertumbuh secara eksponensial dengan risiko terkendali.",
        "folder": "trader_sakti",
        "order": 9
    },
    {
        "id": "ts-m8",
        "filename": "Modul 8 – Dari NOL ke Rp2 Miliar Peta Jalan Manual Trading Sakti.pdf",
        "title": "Modul 8: Peta Jalan Rp2 Miliar Manual Trading",
        "category": "risk_management",
        "description": "Rencana bertahap dan simulasi pertumbuhan portofolio secara nyata dari modal awal menuju target besar.",
        "folder": "trader_sakti",
        "order": 10
    },
    {
        "id": "ts-m9",
        "filename": "Modul 9 – Lo Nggak Perlu Resign Buat Kaya. Trading Manual Bisa Jadi Mesin Duit Kedua Lo!.pdf",
        "title": "Modul 9: Trading Sebagai Sumber Pendapatan Kedua",
        "category": "risk_management",
        "description": "Cara menyeimbangkan trading manual dengan pekerjaan utama tanpa mengorbankan performa kerja.",
        "folder": "trader_sakti",
        "order": 11
    },
    {
        "id": "ts-cutloss-3s",
        "filename": "FORMULA RAHASIA CUT LOSS 3 DETIK 7 Jurus Anti Boncos.pdf",
        "title": "Formula Cut Loss 3 Detik: 7 Jurus Anti Boncos",
        "category": "risk_management",
        "description": "Aturan psikologis dan taktis membuang saham rugi dalam 3 detik sebelum kerugian membengkak.",
        "folder": "trader_sakti",
        "order": 12
    },
    {
        "id": "ts-blueprint",
        "filename": "BLUEPRINT 7 HARI CUAN KONSISTEN.pdf",
        "title": "Blueprint 7 Hari Cuan Konsisten",
        "category": "risk_management",
        "description": "Langkah-langkah harian untuk mendisiplinkan diri dalam trading dan menghasilkan profit teratur.",
        "folder": "trader_sakti",
        "order": 13
    },
    {
        "id": "ts-m5",
        "filename": "Modul 5 Duit Lo Bisa Meledak Tanpa Robot .pdf",
        "title": "Modul 5: Meledakkan Profit Tanpa Robot / Autopilot",
        "category": "strategi",
        "description": "Mengandalkan logika trading manual yang cerdas daripada menyerahkan modal pada algoritma kaku.",
        "folder": "trader_sakti",
        "order": 14
    },
    {
        "id": "ts-bot-ai",
        "filename": "[ONE TIME OFFER, PENAWARAN SEKALI SEUMUR HIDUP] Bot Trading AI.pdf",
        "title": "Bot Trading AI: Konsep & Sistem Otomatis",
        "category": "strategi",
        "description": "Panduan pemanfaatan sistem kecerdasan buatan untuk membantu menyaring sinyal trading.",
        "folder": "trader_sakti",
        "order": 15
    },
    {
        "id": "ai-panduan",
        "filename": "Panduan Strategi Profit Konsisten Dari Trading Harian Saham.pdf",
        "title": "Strategi Profit Konsisten Trading Harian Saham",
        "category": "strategi",
        "description": "Panduan teknis mendalam mengenai taktik beli pagi jual sore (BPJS) dan scalping aman.",
        "folder": "ai_scanner",
        "order": 16
    },
    {
        "id": "ai-sc-7f",
        "filename": "7f84368d-de83-478d-b3e2-dcfc8d5be7bd.pdf",
        "title": "Materi Tambahan: Analisis Teknikal Lanjutan (1)",
        "category": "strategi",
        "description": "Materi referensi visual pola pembalikan harga (reversal) dan analisis grafik tingkat lanjut.",
        "folder": "ai_scanner",
        "order": 17
    },
    {
        "id": "ai-sc-3c",
        "filename": "3cd0fe6a-fa1a-4384-8fec-3bbe174da0bd.pdf",
        "title": "Materi Tambahan: Analisis Teknikal Lanjutan (2)",
        "category": "strategi",
        "description": "Materi referensi visual pola grafik kelanjutan tren (continuation).",
        "folder": "ai_scanner",
        "order": 18
    },
    {
        "id": "ai-sc-77",
        "filename": "7780d657-ad9a-4044-906c-b835e2ada178.pdf",
        "title": "Materi Tambahan: Manajemen Portofolio Taktis",
        "category": "strategi",
        "description": "Panduan melacak kinerja portofolio trading secara manual dan rebalancing berkala.",
        "folder": "ai_scanner",
        "order": 19
    }
]

RESOURCES_METADATA = [
    {
        "id": "res-checklist-24h",
        "filename": "Checklist Anti Boncos 24 Jam.xlsx",
        "title": "Checklist Anti Boncos 24 Jam",
        "description": "Daftar periksa taktis sebelum entry pasar untuk menekan bias emosional/FOMO.",
        "folder": "trader_sakti"
    },
    {
        "id": "res-calc-2m",
        "filename": "KALKULATOR CUAN 2 MILIAR 18 Langkah Compounding Sakti.xlsx",
        "title": "Kalkulator Cuan Rp2 Miliar (Compounding)",
        "description": "Spreadsheet simulasi perencanaan target compounding 18 langkah dengan pertumbuhan saldo teratur.",
        "folder": "trader_sakti"
    },
    {
        "id": "res-log-30d",
        "filename": "Log Trading Sakti Catatan 30 Harian Cuan Manual Trading.xlsx",
        "title": "Jurnal & Log Trading 30 Harian",
        "description": "Buku jurnal harian untuk mencatat evaluasi teknis, emosi, dan persentase profit per transaksi.",
        "folder": "trader_sakti"
    },
    {
        "id": "res-mm-template",
        "filename": "SUPER TEMPLATE Money Management Sakti Rp2 Miliar Roadmap.xlsx",
        "title": "Super Template Money Management Rp2 Miliar",
        "description": "Roadmap alokasi dana dan formula penentuan ukuran posisi (position sizing) berdasarkan risiko.",
        "folder": "trader_sakti"
    },
    {
        "id": "res-mindset-card",
        "filename": "TRADER SAKTI MINDSET CARD 50 Mantra Anti FOMO & Stres.xlsx",
        "title": "50 Mantra Anti-FOMO & Mindset Card",
        "description": "Lembar kartu mental pengingat psikologi trading untuk menjaga disiplin operasional harian.",
        "folder": "trader_sakti"
    },
    {
        "id": "res-toolkit",
        "filename": "TRADER SAKTI TOOLKIT 30 Checklist Wajib Sebelum Entry (Anti Boncos, Anti Nyangkut).xlsx",
        "title": "Toolkit 30 Checklist Sebelum Entry",
        "description": "Toolkit lembar periksa komprehensif pendukung keputusan sebelum mengeksekusi order beli.",
        "folder": "trader_sakti"
    },
    {
        "id": "res-stockhunter-zip",
        "filename": "StockHunter.zip",
        "title": "StockHunter Codebase & Executable",
        "description": "Arsip ZIP berisi kode program StockHunter untuk keperluan pemindaian tambahan.",
        "folder": "ai_scanner"
    }
]

class LearningManager:
    @staticmethod
    def _get_file_path(filename: str, folder: str) -> str:
        base_dir = TRADER_SAKTI_PATH if folder == "trader_sakti" else AI_SCANNER_PATH
        return os.path.join(base_dir, filename)

    @classmethod
    def get_modules_data(cls, force_rescan: bool = False) -> List[Dict[str, Any]]:
        """Mengambil data modul lengkap dengan page count. Menggunakan cache untuk kecepatan."""
        if not force_rescan and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass

        # Jalankan rescan
        scanned_modules = []
        for m in MODULES_METADATA:
            path = cls._get_file_path(m["filename"], m["folder"])
            exists = os.path.exists(path)
            pages = 0
            size_kb = 0

            if exists:
                try:
                    size_kb = round(os.path.getsize(path) / 1024)
                    with pdfplumber.open(path) as pdf:
                        pages = len(pdf.pages)
                except Exception:
                    pages = 1  # Fallback defensif

            scanned_modules.append({
                **m,
                "exists": exists,
                "pages": pages,
                "size_kb": size_kb
            })

        # Simpan ke cache
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(scanned_modules, f, indent=2)
        except Exception:
            pass

        return scanned_modules

    @classmethod
    def get_resources_data(cls) -> List[Dict[str, Any]]:
        """Mengambil daftar sumber daya template pendukung."""
        scanned_res = []
        for r in RESOURCES_METADATA:
            path = cls._get_file_path(r["filename"], r["folder"])
            exists = os.path.exists(path)
            size_kb = 0
            if exists:
                size_kb = round(os.path.getsize(path) / 1024)
            scanned_res.append({
                **r,
                "exists": exists,
                "size_kb": size_kb
            })
        return scanned_res

    @classmethod
    def get_progress(cls) -> Dict[str, bool]:
        """Mengambil progress penyelesaian belajar user."""
        if os.path.exists(PROGRESS_FILE):
            try:
                with open(PROGRESS_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @classmethod
    def update_progress(cls, module_id: str, completed: bool) -> Dict[str, Any]:
        """Menyimpan/memperbarui progress belajar."""
        progress = cls.get_progress()
        progress[module_id] = completed
        
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        try:
            with open(PROGRESS_FILE, "w") as f:
                json.dump(progress, f, indent=2)
        except Exception:
            pass

        # Hitung persentase progress baru
        modules = cls.get_modules_data()
        active_modules = [m for m in modules if m["exists"]]
        total = len(active_modules)
        
        completed_count = sum(1 for m in active_modules if progress.get(m["id"], False))
        pct = round(completed_count / total * 100) if total > 0 else 0

        return {
            "progress": progress,
            "pct": pct,
            "completed_count": completed_count,
            "total_count": total
        }

    @classmethod
    def get_file_response_path(cls, file_id: str, is_resource: bool = False) -> Optional[str]:
        """Mendapatkan path fisik berkas berdasarkan ID-nya (aman dari directory traversal)."""
        if is_resource:
            for r in RESOURCES_METADATA:
                if r["id"] == file_id:
                    path = cls._get_file_path(r["filename"], r["folder"])
                    if os.path.exists(path):
                        return path
        else:
            for m in MODULES_METADATA:
                if m["id"] == file_id:
                    path = cls._get_file_path(m["filename"], m["folder"])
                    if os.path.exists(path):
                        return path
        return None
