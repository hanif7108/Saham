#!/usr/bin/env bash
# Konfigurasi deploy. Sesuaikan lalu: source deploy/config.sh
# --------------------------------------------------------------------------
# Host Mac mini. Bonjour ".local" berfungsi lewat Thunderbolt Bridge & LAN.
# Cek nama: di Mac mini → System Settings → General → About → Name, atau:
#   scutil --get LocalHostName        (mis. menghasilkan "hanifs-mac-mini")
# Bila pakai IP Thunderbolt statis, isi langsung mis. 10.0.0.2
export MACMINI_USER="${MACMINI_USER:-hanif}"

# Fungsi deteksi otomatis koneksi tercepat dengan prioritas:
# 1. Thunderbolt, 2. LAN WiFi, 3. Tailscale VPN
detect_fastest_host() {
    local candidates=("169.254.118.141" "192.168.1.115" "100.107.4.14")
    local names=("Thunderbolt" "LAN (WiFi)" "Tailscale VPN")
    
    local tmp_dir
    tmp_dir=$(mktemp -d 2>/dev/null || mktemp -d -t 'mini_detect')
    
    # Jalankan pengecekan port 22 (SSH) secara paralel
    for i in "${!candidates[@]}"; do
        local ip="${candidates[$i]}"
        local name="${names[$i]}"
        (
            start_time=$(perl -MTime::HiRes=time -e 'print time')
            # Gunakan -G 1 untuk connection timeout 1 detik di macOS (BSD nc)
            if nc -z -G 1 "$ip" 22 2>/dev/null; then
                end_time=$(perl -MTime::HiRes=time -e 'print time')
                diff=$(perl -e "print (($end_time - $start_time) * 1000)")
                echo "$diff $ip $name" > "$tmp_dir/res_$i"
            fi
        ) &
    done
    
    # Tunggu parallel jobs selesai (timeout 1s + 0.2s padding)
    sleep 1.2 2>/dev/null || sleep 1
    
    local selected_ip=""
    local selected_name=""
    local selected_latency=""
    
    # Pilih berdasarkan prioritas indeks (0 -> 1 -> 2)
    for i in "${!candidates[@]}"; do
        if [ -f "$tmp_dir/res_$i" ]; then
            read -r latency ip name < "$tmp_dir/res_$i"
            selected_ip="$ip"
            selected_name="$name"
            selected_latency="$latency"
            break # Berhenti di prioritas tertinggi yang aktif
        fi
    done
    
    rm -rf "$tmp_dir"
    
    if [ -n "$selected_ip" ]; then
        local lat_int
        lat_int=$(perl -e 'print int($ARGV[0])' "$selected_latency")
        echo -e "\033[1;32m⚡ Koneksi Mac Mini Aktif: $selected_name ($selected_ip) - Latency: ${lat_int}ms\033[0m" >&2
        echo "$selected_ip"
    else
        echo -e "\033[1;31m⚠️ Mac Mini tidak terjangkau di semua jalur! Menggunakan default: ${candidates[0]}\033[0m" >&2
        echo "${candidates[0]}"
    fi
}

export MACMINI_HOST=$(detect_fastest_host)

# Lokasi aplikasi di KEDUA komputer (samakan path agar mudah).
export APP_DIR="${APP_DIR:-/Users/hanif/Saham/sharia_trading_ai}"

# Port server.
export APP_PORT="${APP_PORT:-80}"

export MACMINI="${MACMINI_USER}@${MACMINI_HOST}"
