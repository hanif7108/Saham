#!/usr/bin/env bash
# ============================================================
# Sharia TA — Restart Gunicorn dengan kode baru
# ============================================================
# Tujuan: kill SEMUA gunicorn lama yang menguasai port 8000,
# lalu start ulang dengan code & config terbaru.
#
# Jalankan: bash /Users/hanif/Saham/restart_gunicorn.sh
# ============================================================

set -e
SAHAM_DIR="/Users/hanif/Saham"
PORT=8000

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { echo -e "${BLUE}[restart]${NC} $*"; }
ok()  { echo -e "${GREEN}✓${NC} $*"; }
warn(){ echo -e "${YELLOW}!${NC} $*"; }
err() { echo -e "${RED}✗${NC} $*" >&2; }

cd "$SAHAM_DIR"

# ---------- STEP 1: Unload launchd kalau aktif ----------
if launchctl list | grep -q com.shariata.app; then
    warn "launchd agent com.shariata.app sedang AKTIF — unload dulu agar tidak respawn"
    launchctl unload "$HOME/Library/LaunchAgents/com.shariata.app.plist" 2>/dev/null || true
    sleep 1
    ok "launchd agent di-unload"
else
    ok "Tidak ada launchd agent aktif"
fi

# ---------- STEP 2: Kill SEMUA gunicorn yang dengarkan port 8000 ----------
log "Mencari proses di port $PORT ..."
PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    warn "Process menguasai port $PORT: $PIDS"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# Cadangan: kill semua proses yang command-line-nya mengandung "gunicorn"
GUNI=$(pgrep -f "gunicorn" 2>/dev/null || true)
if [ -n "$GUNI" ]; then
    warn "Sisa proses gunicorn: $GUNI — kill"
    echo "$GUNI" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# Kill scheduler proses (yang di-spawn oleh on_starting hook gunicorn lama)
SCHED=$(pgrep -f "run_scheduler.py" 2>/dev/null || true)
if [ -n "$SCHED" ]; then
    warn "Sisa scheduler proses: $SCHED — kill"
    echo "$SCHED" | xargs kill -9 2>/dev/null || true
    sleep 1
fi

# ---------- STEP 3: Verifikasi port BENAR-BENAR kosong ----------
sleep 2
if lsof -ti :$PORT 2>/dev/null | grep -q .; then
    err "Port $PORT MASIH terpakai oleh: $(lsof -ti :$PORT)"
    err "Coba: sudo kill -9 \$(lsof -ti :$PORT)"
    exit 1
fi
ok "Port $PORT bersih"

# ---------- STEP 4: Verifikasi venv & file penting ----------
if [ ! -x "$SAHAM_DIR/venv/bin/python3" ]; then
    err "venv/bin/python3 tidak ditemukan — apakah venv ter-setup?"
    exit 1
fi
if [ ! -f "$SAHAM_DIR/app.py" ] || [ ! -f "$SAHAM_DIR/deploy/gunicorn_config.py" ]; then
    err "app.py atau deploy/gunicorn_config.py hilang"
    exit 1
fi
ok "venv & file penting OK"

# ---------- STEP 5: Quick sanity check — import app.py untuk deteksi error sintaks/import ----------
log "Pre-flight: import app.py untuk pastikan tidak ada ImportError ..."
if ! "$SAHAM_DIR/venv/bin/python3" -c "
import sys; sys.path.insert(0, '$SAHAM_DIR')
import app  # noqa
routes = [str(r) for r in app.app.url_map.iter_rules() if 'dashboard' in str(r)]
print('Routes dengan dashboard:', routes)
assert any('/api/dashboard' in r for r in routes), 'Endpoint /api/dashboard TIDAK terdaftar!'
print('OK')
"; then
    err "Pre-flight gagal — periksa app.py / modules/rebalancer.py untuk error"
    exit 1
fi
ok "Pre-flight: endpoint /api/dashboard terdaftar"

# ---------- STEP 6: Start gunicorn fresh ----------
mkdir -p logs
log "Starting gunicorn ..."
# nohup + disown supaya gunicorn tetap hidup setelah shell tutup
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
nohup "$SAHAM_DIR/venv/bin/python3" -m gunicorn \
      -c "$SAHAM_DIR/deploy/gunicorn_config.py" \
      app:app > logs/gunicorn_nohup.log 2>&1 &
GUNI_PID=$!
disown
ok "Gunicorn launched (parent shell PID: $GUNI_PID) — booting workers..."

# Beri waktu boot
sleep 5

# ---------- STEP 7: Smoke-test endpoint /api/dashboard ----------
log "Smoke-test /api/dashboard ..."
HTTP=$(curl -s -o /tmp/dashboard_smoke.json -w "%{http_code}" --max-time 30 \
       http://127.0.0.1:$PORT/api/dashboard || echo "000")
SIZE=$(wc -c < /tmp/dashboard_smoke.json 2>/dev/null || echo 0)

if [ "$HTTP" = "200" ]; then
    ok "HTTP 200 ($SIZE bytes) — dashboard endpoint AKTIF ✨"
    echo
    log "Sample payload (head 30 lines):"
    "$SAHAM_DIR/venv/bin/python3" -m json.tool /tmp/dashboard_smoke.json 2>/dev/null | head -30 || cat /tmp/dashboard_smoke.json | head -10
    echo
    ok "Buka http://127.0.0.1:$PORT/ di browser & hard-refresh (Cmd+Shift+R)"
elif [ "$HTTP" = "404" ]; then
    err "HTTP 404 — endpoint TIDAK ditemukan. Kemungkinan gunicorn pakai kode lama (cache __pycache__?)."
    log "Coba clear pycache lalu jalankan ulang script ini:"
    log "  rm -rf $SAHAM_DIR/__pycache__ $SAHAM_DIR/modules/__pycache__"
    exit 2
elif [ "$HTTP" = "500" ]; then
    err "HTTP 500 — endpoint crash. Tail log error:"
    tail -40 "$SAHAM_DIR/logs/gunicorn_error.log"
    exit 3
else
    err "HTTP $HTTP — gunicorn mungkin belum siap atau crash. Cek log:"
    log "  tail -40 logs/gunicorn_error.log"
    log "  tail -20 logs/gunicorn_nohup.log"
    tail -20 "$SAHAM_DIR/logs/gunicorn_nohup.log"
    exit 4
fi
