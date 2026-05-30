"""
Telegram Notification
=====================
Kirim alert & rekomendasi via Telegram Bot API.

POST-PATCH (2026-05) — improvements:
  • parse_mode default = HTML (lebih permisif daripada Markdown legacy)
  • Auto-fallback: kalau HTML/Markdown gagal parse, retry plain text
  • Logging proper via `logger` (mirror ke gunicorn_error.log)
  • Truncate ≤4000 chars (Telegram limit 4096)
  • Helper diagnostic: get_me(), get_chat() untuk validasi token & chat
  • Method validate(): satu-stop cek konfigurasi

SETUP (paling mudah lewat wizard):
    bash ~/Saham/setup_telegram.sh

Atau manual:
  1. Buka Telegram, cari "@BotFather" → /newbot → ikuti instruksi
  2. Catat BOT TOKEN dari BotFather
  3. Cari bot Anda di Telegram, ketik /start (perlu agar getUpdates bisa lihat chat)
  4. Buka URL: https://api.telegram.org/bot<TOKEN>/getUpdates
     Cari "chat":{"id": 123456789, ...} → itu CHAT_ID Anda
  5. Edit ~/Saham/.env:
        TELEGRAM_BOT_TOKEN=7891234567:AAH...
        TELEGRAM_CHAT_ID=123456789
        TELEGRAM_ENABLED=true
  6. Restart app: launchctl kickstart -k gui/$(id -u)/com.shariata.app

PENGGUNAAN:
    from modules.telegram_notify import TelegramNotifier
    notif = TelegramNotifier()
    notif.send_text("Hello from Sharia TA")
    notif.send_alerts(alerts_list)
    notif.send_decisions(decisions_dict)
"""

from __future__ import annotations

import html
import logging
import os
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


# --- Load .env (idempotent, tidak override existing env) ---
_ENV_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".env"
)
if os.path.exists(_ENV_FILE):
    try:
        with open(_ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:  # pragma: no cover
        logger.warning("failed loading .env: %s", e)


# Telegram constants
TG_MAX_MESSAGE = 4096
SAFE_TRUNCATE = 4000  # leave ~96 char buffer for safety


class TelegramNotifier:
    """Lightweight Telegram bot client.

    Default parse_mode = HTML untuk kompatibilitas maksimum dengan content
    yang mengandung karakter spesial markdown (mis. ticker SR_AAPL, reason
    text mengandung `_` `*` `[` dst.).
    """

    API_BASE = "https://api.telegram.org"

    def __init__(self,
                 bot_token: Optional[str] = None,
                 chat_id: Optional[str] = None):
        self.bot_token = (bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
        self.chat_id = (chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()

    @property
    def configured(self) -> bool:
        enabled = os.environ.get("TELEGRAM_ENABLED", "true").lower() in {"true", "1", "yes"}
        return enabled and bool(self.bot_token and self.chat_id)

    @property
    def missing_config(self) -> List[str]:
        miss = []
        if os.environ.get("TELEGRAM_ENABLED", "true").lower() not in {"true", "1", "yes"}:
            miss.append("TELEGRAM_ENABLED=true")
        if not self.bot_token:
            miss.append("TELEGRAM_BOT_TOKEN")
        if not self.chat_id:
            miss.append("TELEGRAM_CHAT_ID")
        return miss

    # ---------- Diagnostic helpers ----------

    def get_me(self) -> Dict:
        """Validate token via /getMe. Return bot info atau error."""
        if not self.bot_token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN kosong"}
        try:
            r = requests.get(f"{self.API_BASE}/bot{self.bot_token}/getMe", timeout=10)
            data = r.json()
            if not data.get("ok"):
                return {"ok": False, "error": data.get("description", "unknown"),
                        "status_code": r.status_code}
            return {"ok": True, "bot": data.get("result", {})}
        except requests.RequestException as e:
            return {"ok": False, "error": f"network: {e}"}

    def get_chat(self) -> Dict:
        """Validate chat_id via /getChat. Return chat info atau error."""
        if not (self.bot_token and self.chat_id):
            return {"ok": False, "error": "TOKEN atau CHAT_ID kosong"}
        try:
            r = requests.get(
                f"{self.API_BASE}/bot{self.bot_token}/getChat",
                params={"chat_id": self.chat_id}, timeout=10
            )
            data = r.json()
            if not data.get("ok"):
                return {"ok": False, "error": data.get("description", "unknown"),
                        "status_code": r.status_code}
            return {"ok": True, "chat": data.get("result", {})}
        except requests.RequestException as e:
            return {"ok": False, "error": f"network: {e}"}

    def validate(self) -> Dict:
        """One-stop diagnostic. Cek konfigurasi + token + chat."""
        out = {"configured": self.configured,
               "missing_config": self.missing_config,
               "bot": None, "chat": None}
        if not self.bot_token:
            out["error"] = "TELEGRAM_BOT_TOKEN kosong di .env"
            return out
        me = self.get_me()
        if not me.get("ok"):
            out["error"] = f"Token invalid: {me.get('error')}"
            return out
        out["bot"] = me.get("bot")
        if not self.chat_id:
            out["error"] = "TELEGRAM_CHAT_ID kosong di .env"
            return out
        chat = self.get_chat()
        if not chat.get("ok"):
            out["error"] = (f"Chat ID invalid atau bot belum diizinkan: "
                            f"{chat.get('error')}. Buka Telegram, kirim /start ke bot Anda.")
            return out
        out["chat"] = chat.get("chat")
        out["ok"] = True
        return out

    # ---------- Core send ----------

    def _post_send(self, text: str, parse_mode: Optional[str]) -> Dict:
        """Low-level POST ke sendMessage. Tidak ada fallback."""
        url = f"{self.API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text[:SAFE_TRUNCATE],
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            r = requests.post(url, json=payload, timeout=15)
            data = r.json()
            return {"ok": data.get("ok", False),
                    "status_code": r.status_code,
                    "result": data}
        except requests.RequestException as e:
            return {"ok": False, "error": f"network: {e}"}

    def send_text(self,
                  text: str,
                  parse_mode: str = "HTML",
                  disable_preview: bool = True) -> Dict:
        """Kirim text. Default HTML mode. Auto-fallback ke plain kalau parse fail.

        disable_preview parameter retained untuk backward compat (sebenarnya
        sudah hardcoded ke True di _post_send).
        """
        if not self.configured:
            return {"ok": False,
                    "error": "Telegram belum dikonfigurasi: " + ", ".join(self.missing_config)}

        if len(text) > TG_MAX_MESSAGE:
            logger.info("Telegram message truncated %d → %d chars", len(text), SAFE_TRUNCATE)

        # 1) Try with parse_mode
        result = self._post_send(text, parse_mode)
        if result.get("ok"):
            return result

        # 2) Inspect error — kalau parse error, fallback ke plain text
        err_desc = ""
        if isinstance(result.get("result"), dict):
            err_desc = result["result"].get("description", "") or ""

        parse_error_signs = [
            "can't parse entities",
            "bad request: can't parse",
            "unsupported start tag",
            "unmatched end tag",
            "unsupported tag",
        ]
        is_parse_error = any(s in err_desc.lower() for s in parse_error_signs)

        if is_parse_error:
            logger.warning("Telegram %s parse failed (%s) — retry plain text",
                           parse_mode, err_desc)
            # Plain text: strip all HTML/markdown markers
            plain = _strip_html_tags(text) if parse_mode == "HTML" else text
            result_plain = self._post_send(plain, None)
            if result_plain.get("ok"):
                result_plain["fallback"] = "plain_text"
                return result_plain
            logger.error("Telegram plain text fallback also failed: %s", result_plain)
            return result_plain

        logger.error("Telegram send failed: status=%s desc=%s",
                     result.get("status_code"), err_desc or result.get("error"))
        return result

    # ---------- High-level senders (HTML mode) ----------

    def send_test(self) -> Dict:
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = (
            "✅ <b>Sharia Trading Assistant — Test</b>\n\n"
            f"Bot Anda terhubung dengan benar pada {html.escape(ts)}.\n"
            "Mulai sekarang, alert dan rekomendasi akan dikirim ke chat ini."
        )
        return self.send_text(text)

    def send_alerts(self, alerts: List[Dict],
                    min_severity: str = "medium") -> Dict:
        if not alerts:
            return {"ok": True, "skipped": "no alerts"}

        sev_rank = {"low": 0, "medium": 1, "high": 2}
        threshold = sev_rank.get(min_severity, 1)
        filtered = [a for a in alerts
                    if sev_rank.get(a.get("severity", "medium"), 1) >= threshold]
        if not filtered:
            return {"ok": True, "skipped": "no alerts above threshold"}

        high = [a for a in filtered if a.get("severity") == "high"]
        med = [a for a in filtered if a.get("severity") == "medium"]

        lines = ["🔔 <b>Sharia TA — Alert</b>\n"]
        if high:
            lines.append(f"🚨 <b>PRIORITY HIGH</b> ({len(high)})")
            for a in high:
                t = html.escape(str(a.get("ticker", "?")))
                m = html.escape(str(a.get("message", "")))
                lines.append(f"  • <b>{t}</b> — {m}")
        if med:
            lines.append(f"\n⚠️ <b>PRIORITY MEDIUM</b> ({len(med)})")
            for a in med:
                t = html.escape(str(a.get("ticker", "?")))
                m = html.escape(str(a.get("message", "")))
                lines.append(f"  • <b>{t}</b> — {m}")

        return self.send_text("\n".join(lines))

    def send_decisions(self, decisions: Dict) -> Dict:
        s = decisions.get("summary", {})
        verdict = s.get("verdict", "—")
        n_sell = s.get("n_sell", 0)
        n_buy = s.get("n_buy", 0)
        n_hold = s.get("n_hold", 0)

        lines = [
            "📊 <b>Sharia TA — Rekomendasi Hari Ini</b>\n",
            f"<i>{html.escape(str(verdict))}</i>\n",
            f"📈 BUY: <b>{n_buy}</b>  📉 SELL: <b>{n_sell}</b>  ⏸ HOLD: <b>{n_hold}</b>\n",
        ]

        if decisions.get("sell"):
            lines.append("\n🔴 <b>AKSI JUAL:</b>")
            for x in decisions["sell"][:5]:
                urg = html.escape(str(x.get("urgency", "")))
                tk = html.escape(str(x.get("ticker", "?")))
                rs = html.escape(str(x.get("reason", "")))
                lines.append(f"  • [{urg}] <b>{tk}</b> — {rs}")
                if x.get("next_step"):
                    lines.append(f"     → <i>{html.escape(str(x['next_step']))}</i>")

        if decisions.get("buy"):
            lines.append("\n🟢 <b>PELUANG BELI:</b>")
            for x in decisions["buy"][:5]:
                urg = html.escape(str(x.get("urgency", "")))
                conf = html.escape(str(x.get("confidence", "")))
                tk = html.escape(str(x.get("ticker", "?")))
                rs = html.escape(str(x.get("reason", "")))
                lines.append(f"  • [{urg}/{conf}] <b>{tk}</b> — {rs}")
                if x.get("next_step"):
                    lines.append(f"     → <i>{html.escape(str(x['next_step']))}</i>")

        return self.send_text("\n".join(lines))

    # ---------- DASHBOARD STRUCTURED MESSAGE ----------

    def send_dashboard_summary(self,
                               dashboard: Dict,
                               us_action_plan: Optional[Dict] = None,
                               us_top5: Optional[List[Dict]] = None) -> Dict:
        """Format payload /api/dashboard jadi pesan terstruktur 6-section.

        Args:
            dashboard: payload dari GET /api/dashboard
            us_action_plan: payload dari GET /api/us/action_plan (opsional)
            us_top5: list dari GET /api/us/top5.data (opsional)

        Strategi: 1 pesan compact (≤4000 char). Section yang None/kosong di-skip.
        """
        if not self.configured:
            return {"ok": False,
                    "error": "Telegram belum dikonfigurasi: " + ", ".join(self.missing_config)}

        # ----------- HEADER -----------
        from datetime import datetime
        now = datetime.now().strftime("%d %b %Y, %H:%M WIB")

        lines: List[str] = []
        lines.append("📊 <b>SHARIA TA — DASHBOARD HARIAN</b>")
        lines.append(f"<i>{html.escape(now)}</i>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # ----------- STATUS PASAR -----------
        ihsg = (dashboard or {}).get("ihsg") or {}
        market = (dashboard or {}).get("market") or {}
        ihsg_close = ihsg.get("ihsg_close") or ihsg.get("last")
        ihsg_ma50 = ihsg.get("ihsg_ma50") or ihsg.get("ma50")
        ihsg_status = ihsg.get("status") or market.get("badge") or "?"
        delta = None
        if ihsg_close and ihsg_ma50 and ihsg_ma50 > 0:
            delta = (ihsg_close - ihsg_ma50) / ihsg_ma50 * 100
        ihsg_str = f"IHSG: <b>{_fmt_num(ihsg_close)}</b>"
        if delta is not None:
            ihsg_str += f" ({delta:+.2f}% vs MA50)"
        ihsg_str += f" — {html.escape(str(ihsg_status))}"
        lines.append(f"🇮🇩 {ihsg_str}")

        # US market status (kalau ada dalam health endpoint sebenarnya, tapi
        # us_action_plan punya snapshot via cache history)
        usdidr = (us_action_plan or {}).get("usdidr_rate")
        if usdidr:
            lines.append(f"💱 USDIDR: <b>{_fmt_num(usdidr)}</b>")

        # ----------- VERDICT HARIAN -----------
        verdict = (dashboard or {}).get("verdict")
        if verdict:
            lines.append("")
            lines.append(f"<i>{html.escape(str(verdict))}</i>")

        # ----------- PORTFOLIO -----------
        portfolio = (dashboard or {}).get("portfolio") or {}
        if portfolio:
            lines.append("")
            lines.append("💼 <b>PORTFOLIO</b>")
            total_rp = portfolio.get("total_asset_rp") or portfolio.get("total_value_rp") or 0
            pnl_pct = portfolio.get("pnl_pct")
            pnl_str = f" | P/L: <b>{pnl_pct:+.2f}%</b>" if pnl_pct is not None else ""
            lines.append(f"  Total: <b>{_fmt_rp(total_rp)}</b>{pnl_str}")
            holdings = portfolio.get("holdings") or []
            for h in holdings[:5]:  # cap 5 holding
                tk = html.escape(str(h.get("ticker", "?")))
                lot = h.get("lot") or 0
                hb = h.get("harga_beli") or 0
                cur = h.get("sekarang") or h.get("current_price") or 0
                pnl = h.get("pnl") or 0
                aksi = html.escape(str(h.get("aksi", "")))
                emoji = "🟢" if pnl >= 0 else "🔴"
                lines.append(
                    f"  {emoji} <b>{tk}</b>: {lot} lot @ {_fmt_num(hb)} → {_fmt_num(cur)} "
                    f"| <b>{pnl:+.2f}%</b> | {aksi}"
                )
            if len(holdings) > 5:
                lines.append(f"  <i>(+{len(holdings)-5} ticker lain)</i>")

        # ----------- ALOKASI TARGET (4-bucket) -----------
        alloc = (dashboard or {}).get("allocation") or {}
        target = alloc.get("target") or {}
        current = alloc.get("current") or {}
        amounts = alloc.get("amounts") or {}
        if target:
            lines.append("")
            lines.append("📊 <b>ALOKASI TARGET</b>")
            buckets = [
                ("🇮🇩 IDX ", "saham_idx"),
                ("🇺🇸 US  ", "saham_us"),
                ("🪙 Emas", "emas"),
                ("💵 Cash", "cash"),
            ]
            for label, key in buckets:
                if key not in target and key not in ("saham_idx", "saham_us"):
                    continue
                tp = (target.get(key, 0) or 0) * 100
                cp = (current.get(key, 0) or 0) * 100
                gap_rp = (amounts.get("gap_rp", {}) or {}).get(key, 0)
                gap_str = ""
                if gap_rp and abs(gap_rp) > 50_000:
                    arrow = "akumulasi" if gap_rp > 0 else "kurangi"
                    gap_str = f" ({arrow} {_fmt_rp(abs(gap_rp))})"
                lines.append(
                    f"  {label}: target <b>{tp:.0f}%</b> ← current {cp:.0f}%{gap_str}"
                )

        # ----------- ACTION PLAN IDX -----------
        ap_idx = (dashboard or {}).get("action_plan") or {}
        idx_actions = ap_idx.get("top_actions") or []
        if idx_actions:
            lines.append("")
            lines.append(
                f"🎯 <b>ACTION PLAN IDX</b> ({ap_idx.get('n_sell',0)} SELL · {ap_idx.get('n_buy',0)} BUY)"
            )
            for a in idx_actions[:3]:
                _append_action_idx(lines, a)

        # ----------- ACTION PLAN US -----------
        us_actions = (us_action_plan or {}).get("top_actions") or []
        if us_actions:
            lines.append("")
            lines.append(
                f"🎯 <b>ACTION PLAN US</b> ({us_action_plan.get('n_sell',0)} SELL · {us_action_plan.get('n_buy',0)} BUY)"
            )
            for a in us_actions[:3]:
                _append_action_us(lines, a)

        # ----------- TOP 5 IDX -----------
        top5_idx = (dashboard or {}).get("top5") or []
        if top5_idx:
            lines.append("")
            lines.append("⭐ <b>TOP 5 SAHAM SYARIAH IDX</b>")
            for i, s in enumerate(top5_idx[:5], 1):
                tk = html.escape(str(s.get("ticker", "?")))
                sec = html.escape(str(s.get("sector", ""))[:18])
                sc = s.get("score") or s.get("fundamental_score")
                sc_max = s.get("max_score") or s.get("fundamental_max") or 8
                rsi = s.get("rsi")
                extra = []
                if sc is not None:
                    extra.append(f"Skor {sc}/{sc_max}")
                if rsi is not None:
                    extra.append(f"RSI {rsi:.0f}")
                extra_str = " | ".join(extra) if extra else ""
                lines.append(f"  {i}. <b>{tk}</b> — {sec} | {extra_str}")

        # ----------- TOP 5 US -----------
        if us_top5:
            lines.append("")
            lines.append("⭐ <b>TOP 5 SAHAM SYARIAH US</b> (AAOIFI)")
            for i, s in enumerate(us_top5[:5], 1):
                tk = html.escape(str(s.get("ticker", "?")))
                sec = html.escape(str(s.get("sector", ""))[:18])
                roe = s.get("roe", "")
                per = s.get("per", "")
                st = s.get("aaoifi_status", "")
                emoji = "🟢" if st == "PASS" else "🟡"
                lines.append(
                    f"  {i}. {emoji} <b>{tk}</b> — {sec} | ROE {roe} | PER {per}"
                )

        # ----------- KOMODITAS -----------
        comm = (dashboard or {}).get("commodities") or {}
        gold = comm.get("gold_idr_per_gram") or comm.get("emas_idr_per_gram")
        if gold:
            lines.append("")
            lines.append("🪙 <b>KOMODITAS</b>")
            lines.append(f"  Emas: <b>{_fmt_rp(gold)}</b>/gram")
            silver = comm.get("silver_idr_per_gram")
            if silver:
                lines.append(f"  Perak: {_fmt_rp(silver)}/gram")

        # ----------- ALERT AKTIF -----------
        alerts = (dashboard or {}).get("alerts") or []
        if alerts:
            n = (dashboard or {}).get("alerts_count") or len(alerts)
            lines.append("")
            lines.append(f"🔔 <b>ALERT AKTIF</b> ({n})")
            for a in alerts[:5]:
                sev = (a.get("severity") or "").upper()
                tk = html.escape(str(a.get("ticker", "?")))
                msg = html.escape(str(a.get("message", a.get("type", ""))))
                lines.append(f"  • [{sev}] <b>{tk}</b>: {msg}")
            if n > 5:
                lines.append(f"  <i>(+{n-5} alert lain)</i>")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("<i>Buka dashboard untuk detail lengkap.</i>")

        return self.send_text("\n".join(lines))

    def send_portfolio_summary(self, portfolio: List[Dict]) -> Dict:
        if not portfolio:
            return self.send_text("📂 <b>Portfolio kosong</b> — belum ada posisi.")

        lines = ["💼 <b>Portfolio Summary</b>\n"]
        total_pnl = 0.0
        for p in portfolio:
            pnl = p.get("pnl", 0) or 0
            total_pnl += pnl
            emoji = "🟢" if pnl >= 0 else "🔴"
            tk = html.escape(str(p.get("ticker", "?")))
            aksi = html.escape(str(p.get("aksi", "")))
            try:
                hb = float(p.get("harga_beli", 0) or 0)
                lot = int(p.get("lot", 0) or 0)
            except Exception:
                hb, lot = 0.0, 0
            lines.append(
                f"{emoji} <b>{tk}</b> — beli {hb:,.0f} × {lot} lot | "
                f"<b>{pnl:+.2f}%</b> | {aksi}"
            )
        avg_pnl = total_pnl / len(portfolio) if portfolio else 0
        lines.append(f"\n<i>Rata-rata P/L: <b>{avg_pnl:+.2f}%</b></i>")
        return self.send_text("\n".join(lines))


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags untuk plain-text fallback."""
    import re
    # Remove tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape entities
    text = html.unescape(text)
    return text


# ---------- Format helpers untuk send_dashboard_summary ----------

def _fmt_num(n) -> str:
    """Format angka generik dengan thousand separator."""
    if n is None or n == 0:
        return "–"
    try:
        n = float(n)
        if abs(n) >= 1000:
            return f"{n:,.0f}".replace(",", ".")
        return f"{n:.2f}"
    except (TypeError, ValueError):
        return "–"


def _fmt_rp(n) -> str:
    """Format Rupiah pendek (jt/M/T)."""
    if n is None:
        return "–"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "–"
    abs_n = abs(n)
    if abs_n >= 1e12:
        return f"Rp {n/1e12:.2f} T"
    if abs_n >= 1e9:
        return f"Rp {n/1e9:.2f} M"
    if abs_n >= 1e6:
        return f"Rp {n/1e6:.2f} jt"
    if abs_n >= 1e3:
        return f"Rp {n/1e3:.0f} rb"
    return f"Rp {n:.0f}"


def _fmt_usd(n) -> str:
    """Format USD compact."""
    if n is None:
        return "–"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "–"
    if abs(n) >= 1e6:
        return f"${n/1e6:.2f}M"
    if abs(n) >= 1e3:
        return f"${n/1e3:.2f}K"
    return f"${n:.2f}"


def _append_action_idx(lines: List[str], a: Dict) -> None:
    """Render satu item action plan IDX dalam HTML untuk Telegram."""
    action = (a.get("action") or "?").upper()
    tk = html.escape(str(a.get("ticker", "?")))
    urg = html.escape(str(a.get("urgency", "")))
    reason = html.escape(str(a.get("reason", a.get("reasoning", ""))))
    emoji = "🔴" if action == "SELL" else ("🟢" if action == "BUY" else "⏸")
    lines.append(f"  {emoji} [{urg}] <b>{action} {tk}</b> — {reason}")
    s = a.get("sizing") or {}
    if s.get("lot", 0) > 0 and s.get("amount_rp", 0) > 0:
        if action == "BUY":
            lines.append(
                f"     💰 {s['lot']} lot @ {_fmt_num(s.get('price'))} = "
                f"<b>{_fmt_rp(s.get('amount_rp'))}</b>"
            )
        elif action == "SELL":
            lines.append(
                f"     💸 {s['lot']} lot @ {_fmt_num(s.get('price'))} = "
                f"terima <b>{_fmt_rp(s.get('amount_rp'))}</b>"
            )


def _append_action_us(lines: List[str], a: Dict) -> None:
    """Render satu item action plan US dalam HTML untuk Telegram."""
    action = (a.get("action") or "?").upper()
    tk = html.escape(str(a.get("ticker", "?")))
    urg = html.escape(str(a.get("urgency", "")))
    reason = html.escape(str(a.get("reason", a.get("reasoning", ""))))
    emoji = "🔴" if action == "SELL" else ("🟢" if action == "BUY" else "⏸")
    lines.append(f"  {emoji} [{urg}] <b>{action} {tk}</b> — {reason}")
    s = a.get("sizing") or {}
    if s.get("lot", 0) > 0:
        if action == "BUY":
            lines.append(
                f"     💰 {s['lot']} share @ {_fmt_usd(s.get('price'))} = "
                f"<b>{_fmt_usd(s.get('amount_usd'))}</b> "
                f"({_fmt_rp(s.get('amount_rp'))})"
            )
        elif action == "SELL":
            lines.append(
                f"     💸 {s['lot']} share @ {_fmt_usd(s.get('price'))} = "
                f"terima <b>{_fmt_usd(s.get('amount_usd'))}</b> "
                f"({_fmt_rp(s.get('amount_rp'))})"
            )
    elif s.get("price"):
        lines.append(
            f"     ℹ️ Harga {_fmt_usd(s.get('price'))} > budget per-ticker. "
            f"Pluang support fractional dari $1."
        )


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    notif = TelegramNotifier()
    print(f"Configured: {notif.configured}")
    if notif.configured:
        v = notif.validate()
        print(f"Validate: {v}")
        if v.get("ok"):
            r = notif.send_test()
            print(f"Test result: {r}")
    else:
        print(f"Missing: {notif.missing_config}")
        print("Tip: jalankan `bash ~/Saham/setup_telegram.sh` untuk wizard interaktif.")
