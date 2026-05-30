"""
Gunicorn config untuk Sharia Trading Assistant
==============================================
Run: gunicorn -c deploy/gunicorn_config.py app:app

Catatan post-patch PERBAIKAN_SAHAM.md:
  • preload_app = False    → scheduler aman start setelah fork (preload + fork
                             bisa bikin APScheduler / threading bermasalah).
  • workers default 1      → personal use; yfinance gampang rate-limit kalau
                             banyak worker parallel fetch saat scheduler scan.
                             Override via env: GUNICORN_WORKERS=4.
  • threads = 4            → tetap multi-thread per worker untuk Flask I/O.
"""

import os
import subprocess

# macOS fork safety bypass for libraries like matplotlib/pandas
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")

# Bind & port
bind = os.environ.get("GUNICORN_BIND", "127.0.0.1:8000")

# Worker tuning
# Default 1 worker (sesuai PERBAIKAN_SAHAM.md). Bisa override via env.
workers = int(os.environ.get("GUNICORN_WORKERS", "1"))
worker_class = "gthread"
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
keepalive = 5

# Logging
SAHAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
accesslog = os.path.join(SAHAM_DIR, "logs", "gunicorn_access.log")
errorlog = os.path.join(SAHAM_DIR, "logs", "gunicorn_error.log")
loglevel = "info"

# Process naming
proc_name = "sharia-ta"

# Preload OFF (post-patch). Dengan preload_app=True, scheduler bisa start
# sebelum fork lalu di-duplikat ke semua worker (event loop bisa hang /
# multiprocessing kacau). Dengan preload_app=False, setiap worker import app
# secara independen → _maybe_start_scheduler() di app.py kalau dipanggil akan
# di-skip oleh worker setelah yang pertama, jadi aman & idempotent.
preload_app = False

# Buat folder log kalau belum ada
os.makedirs(os.path.dirname(accesslog), exist_ok=True)


# ---------- GUNICORN LIFECYCLE HOOKS ---------- #
# Otomatis start/stop scheduler.py sebagai subprocess terpisah agar tidak
# tergantung worker (kalau worker restart, scheduler tidak ikut die).
#
# CATATAN: Setelah patch, scheduler juga di-auto-start di dalam app.py via
# _maybe_start_scheduler() saat module load. Dua jalur ini saling backup:
#   - Subprocess di sini: jaminan scheduler tetap hidup meski preload_app=False.
#   - Module-level di app.py: aktif juga di dev mode `python app.py` tanpa
#     gunicorn. Idempotent — kalau sudah ada APScheduler running di proses
#     yang sama, panggilan kedua return early.
scheduler_proc = None


def on_starting(server):
    global scheduler_proc
    log_file_path = os.path.join(SAHAM_DIR, "logs", "scheduler_process.log")
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    print(f"[gunicorn] Starting background scheduler process, logging to {log_file_path} ...")
    try:
        log_file = open(log_file_path, "a", encoding="utf-8")

        # Pake python interpreter dari venv jika ada, fallback ke default python3
        venv_python = os.path.join(SAHAM_DIR, "venv", "bin", "python3")
        python_exec = venv_python if os.path.exists(venv_python) else "python3"

        scheduler_proc = subprocess.Popen(
            [python_exec, os.path.join(SAHAM_DIR, "run_scheduler.py")],
            stdout=log_file,
            stderr=log_file,
            cwd=SAHAM_DIR,
            preexec_fn=os.setsid,
        )
        print(f"[gunicorn] Scheduler process started successfully (PID: {scheduler_proc.pid})")
    except Exception as e:
        print(f"[gunicorn] FAILED to start scheduler process: {e}")


def on_exit(server):
    global scheduler_proc
    if scheduler_proc is not None:
        print(f"[gunicorn] Terminating scheduler process group (PID: {scheduler_proc.pid}) ...")
        try:
            import signal
            os.killpg(os.getpgid(scheduler_proc.pid), signal.SIGTERM)
            scheduler_proc.wait(timeout=5)
            print("[gunicorn] Scheduler process terminated successfully.")
        except Exception as e:
            print(f"[gunicorn] Error stopping scheduler process: {e}")
