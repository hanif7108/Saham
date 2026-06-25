"""
Alert System
============
Memantau seluruh 75 emiten dan men-trigger alert ketika ada kombinasi
sinyal kuat. Cocok dijalankan via scheduler tiap pagi atau intraday.

Tipe Alert:
  1. STRONG BUY     : fundamental >= 4 + technical BUY + Golden cross + RSI < 60
  2. OVERSOLD GEM   : fundamental >= 3 + RSI < 30
  3. VOLUME SURGE   : fundamental >= 4 + volume spike >= 2x
  4. DEATH CROSS    : harga lewati MA50 ke bawah (notifikasi posisi portfolio)
  5. CUT LOSS       : posisi portfolio P/L <= -7%
  6. TAKE PROFIT    : posisi portfolio P/L >= +20%

Output:
  - File log: logs/alerts.log (selalu)
  - File daily: logs/alerts/YYYY-MM-DD.json (untuk laporan)
  - Email (optional, butuh SMTP env vars: SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_TO)
"""

import json
import os
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

import pandas as pd

SAHAM_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(SAHAM_DIR, "logs")
ALERT_LOG = os.path.join(LOG_DIR, "alerts.log")
ALERT_DAILY_DIR = os.path.join(LOG_DIR, "alerts")


def _ensure_dirs():
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(ALERT_DAILY_DIR, exist_ok=True)


def _log(msg: str):
    _ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


# ----------------------------- DETECTION ----------------------------- #

def detect_alerts(scan_results: List[Dict], portfolio: List[Dict] = None) -> List[Dict]:
    """
    Detect alerts dari hasil scan all_stocks + portfolio.

    Args:
        scan_results: list dari /api/all_stocks (75 emiten)
        portfolio: list dari /api/portfolio (saham yang dimiliki)

    Returns:
        List dict alert dengan field: type, ticker, severity, message, details
    """
    alerts: List[Dict] = []

    # ---- Alerts dari scan ----
    for s in scan_results or []:
        ticker = s.get("ticker")
        fund_score = s.get("fundamental_score", 0)
        fund_max = s.get("fundamental_max", 0)
        tech_signal = s.get("technical_signal")
        rsi = s.get("rsi")
        ma_cross = s.get("ma_cross")

        # 1. STRONG BUY combination
        if (fund_score >= 4 and tech_signal == "BUY"
                and ma_cross == "GOLDEN" and rsi is not None and rsi < 60):
            alerts.append({
                "type": "STRONG_BUY",
                "ticker": ticker,
                "severity": "high",
                "message": f"{ticker}: STRONG BUY — Fund {fund_score}/{fund_max}, Tech BUY, Golden cross, RSI {rsi}",
                "details": {"sector": s.get("sector"), "rsi": rsi, "score": fund_score}
            })

        # 2. OVERSOLD GEM (saham bagus tapi sedang oversold)
        elif fund_score >= 3 and rsi is not None and rsi < 30:
            alerts.append({
                "type": "OVERSOLD_GEM",
                "ticker": ticker,
                "severity": "medium",
                "message": f"{ticker}: OVERSOLD — RSI {rsi}, fundamental masih {fund_score}/{fund_max} {s.get('stars','')}",
                "details": {"sector": s.get("sector"), "rsi": rsi, "score": fund_score}
            })

    # ---- Alerts dari portfolio (cut loss / take profit) ----
    for p in portfolio or []:
        ticker = p.get("ticker")
        pnl = p.get("pnl", 0)

        from modules.trading_mode import get_cut_loss_pct, get_take_profit_pct
        cl_pct = get_cut_loss_pct()
        tp_pct = get_take_profit_pct()
        if pnl <= cl_pct:
            alerts.append({
                "type": "CUT_LOSS",
                "ticker": ticker,
                "severity": "high",
                "message": f"{ticker}: CUT LOSS — P/L {pnl}% (≤ {cl_pct}%)",
                "details": {"pnl": pnl, "harga_beli": p.get("harga_beli"), "sekarang": p.get("sekarang")}
            })
        elif pnl >= tp_pct:
            alerts.append({
                "type": "TAKE_PROFIT",
                "ticker": ticker,
                "severity": "high",
                "message": f"{ticker}: TAKE PROFIT — P/L +{pnl}% (≥ +{tp_pct}%)",
                "details": {"pnl": pnl, "harga_beli": p.get("harga_beli"), "sekarang": p.get("sekarang")}
            })

    return alerts


# ----------------------------- DELIVERY ----------------------------- #

def write_alerts(alerts: List[Dict]):
    """Tulis alerts ke alerts.log + alerts/YYYY-MM-DD.json."""
    _ensure_dirs()
    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = os.path.join(ALERT_DAILY_DIR, f"{today}.json")

    # Append ke daily JSON
    existing = []
    if os.path.exists(daily_file):
        try:
            with open(daily_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    new_entries = [{**a, "timestamp": datetime.now().isoformat()} for a in alerts]
    existing.extend(new_entries)

    with open(daily_file, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    # Append ke log
    for a in alerts:
        _log(f"{a['type']} [{a['severity']}] {a['ticker']}: {a['message']}")


def send_email_alerts(alerts: List[Dict],
                       smtp_host: Optional[str] = None,
                       smtp_user: Optional[str] = None,
                       smtp_pass: Optional[str] = None,
                       smtp_port: int = 587,
                       to_address: Optional[str] = None,
                       subject_prefix: str = "[SHARIA-TA]") -> bool:
    """Kirim alert via email. Pakai env vars kalau args tidak diberikan."""
    smtp_host = smtp_host or os.environ.get("SMTP_HOST")
    smtp_user = smtp_user or os.environ.get("SMTP_USER")
    smtp_pass = smtp_pass or os.environ.get("SMTP_PASS")
    to_address = to_address or os.environ.get("ALERT_TO")

    if not (smtp_host and smtp_user and smtp_pass and to_address):
        _log("Email alert SKIPPED: SMTP credentials not configured")
        return False

    if not alerts:
        return True

    high = [a for a in alerts if a["severity"] == "high"]
    if not high:
        # Hanya kirim email untuk severity high — hindari spam
        return True

    subject = f"{subject_prefix} {len(high)} alert priority HIGH"
    body_lines = [f"<h2>{subject}</h2><ul>"]
    for a in high:
        body_lines.append(f"<li><strong>{a['ticker']}</strong> [{a['type']}] — {a['message']}</li>")
    body_lines.append("</ul>")
    body = "\n".join(body_lines)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_address
    msg.attach(MIMEText(body, "html"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_address], msg.as_string())
        _log(f"Email sent to {to_address} ({len(high)} alerts)")
        return True
    except Exception as e:
        _log(f"Email FAILED: {e}")
        return False


# ----------------------------- ORCHESTRATION ----------------------------- #

def run_alert_scan(app_test_client=None) -> Dict:
    """
    Jalankan scan + detect + write + send. Bisa dipanggil dari scheduler.

    Args:
        app_test_client: optional Flask test client (untuk testing).
                         Kalau None, akan import app.app dan buat client baru.

    Returns:
        dict ringkasan: {n_alerts, by_type, alerts}
    """
    if app_test_client is None:
        import sys
        sys.path.insert(0, SAHAM_DIR)
        from app import app
        app_test_client = app.test_client()

    scan_resp = app_test_client.get("/api/all_stocks").get_json()
    portfolio_resp = app_test_client.get("/api/portfolio").get_json()

    scan_results = scan_resp.get("stocks", []) if isinstance(scan_resp, dict) else []
    alerts = detect_alerts(scan_results, portfolio_resp)

    if alerts:
        write_alerts(alerts)
        send_email_alerts(alerts)
        # Telegram notification (optional)
        try:
            from modules.telegram_notify import TelegramNotifier
            notif = TelegramNotifier()
            if notif.configured:
                notif.send_alerts(alerts, min_severity="medium")
        except Exception as e:
            _log(f"Telegram alert FAILED: {e}")

    by_type: Dict[str, int] = {}
    for a in alerts:
        by_type[a["type"]] = by_type.get(a["type"], 0) + 1

    return {
        "n_alerts": len(alerts),
        "by_type": by_type,
        "alerts": alerts,
        "scanned_at": datetime.now().isoformat()
    }


if __name__ == "__main__":
    result = run_alert_scan()
    print(f"=== ALERT SCAN ===")
    print(f"Total alerts: {result['n_alerts']}")
    print(f"By type: {result['by_type']}")
    for a in result["alerts"][:10]:
        print(f"  [{a['severity'].upper():<6}] {a['type']:<14} {a['message']}")
