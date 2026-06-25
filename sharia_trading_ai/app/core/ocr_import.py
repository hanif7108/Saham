"""
Impor portofolio via OCR LOKAL (Tesseract) + parser tabel — TANPA LLM.

Pengganti vision LLM (Gemini sering salah baca angka). Deterministik:
  - Gambar  : Tesseract OCR (image_to_data, posisi kata) → rekonstruksi baris/kolom.
  - PDF      : pdfplumber (extract_tables / text) — paling akurat utk e-statement.

Hasil tetap di-normalisasi & avg dihitung dari last+P/L bila perlu (reuse
vision_import._normalize). Tabel hasil bisa diedit pengguna sebelum impor.
"""

from __future__ import annotations

import io
import re
from typing import Any, Optional

from app.core.vision_import import _norm_broker, _normalize

HDR_EXCLUDE = {"LOT", "AVG", "AVE", "LAST", "PREV", "RP", "PL", "PNL", "BUY", "SELL",
               "NAV", "IDR", "QTY", "TP", "SL", "ALL", "NEW", "ATL", "ATH", "PT", "TBK",
               "VAL", "MKT", "AVL", "USD", "EOD", "LTP", "NET", "GTC",
               # kata umum pada header/teks legal e-statement (bukan ticker)
               "TOTAL", "CASH", "VALUE", "RATIO", "BONDS", "NAME", "PHONE", "PRICE",
               "RDN", "SID", "SRE", "THE", "IDE", "TAMAN", "THIS", "FOR", "AND",
               "OPINI", "HUKUM", "DEWAN", "DARI", "PASAR", "UTANG", "YANG", "USAHA",
               "TIDAK", "EFEK", "BULAN", "DATE", "NO", "CODE", "TYPE", "FUND", "UNIT"}

COL_KEYS = {
    "lots": ["lot", "lots"],
    "avg_price": ["avg", "average", "ratarata", "rata-rata", "avgprice", "modal", "harga rata"],
    "last_price": ["last", "ltp", "prev", "market price", "currentprice", "current", "now"],
    "value": ["value", "nilai", "marketvalue", "market value", "mktval"],
    "pl": ["gain", "loss", "gainloss", "p/l", "pl", "pnl", "floating", "unreal", "profit"],
}


def _idr(tok: str) -> Optional[float]:
    """Parse angka format Indonesia ATAU internasional/US, otomatis terdeteksi.

    ID : '2.100'→2100, '1.880.000'→1880000, '1,42'→1.42, '(15.000)'→-15000
    US : '2,730.00'→2730, '1,100,000'→1100000, '0.73%'→0.73, '705.00'→705
    Aturan: bila dua pemisah hadir → yang paling kanan = desimal. Bila satu jenis
    & gugus terakhir 3 digit → ribuan; selain itu → desimal.
    """
    t = str(tok).strip().replace("Rp", "").replace(" ", "")
    if not t or t in ("-", "—", "–"):
        return None
    neg = t.startswith("(") or t.startswith("-")
    t = t.strip("()").lstrip("+-").rstrip("%")
    if not re.search(r"\d", t):
        return None
    has_c, has_d = "," in t, "." in t
    if has_c and has_d:                       # dua pemisah → kanan = desimal
        if t.rfind(",") > t.rfind("."):       # 2.730,00 (ID)
            t = t.replace(".", "").replace(",", ".")
        else:                                 # 2,730.00 (US)
            t = t.replace(",", "")
    elif has_c:                               # hanya koma
        parts = t.split(",")
        t = t.replace(",", ".") if (len(parts) == 2 and len(parts[1]) != 3) else t.replace(",", "")
    elif has_d:                               # hanya titik
        parts = t.split(".")
        if not (len(parts) == 2 and len(parts[1]) != 3):   # ribuan → buang titik
            t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _is_ticker(s: str) -> bool:
    return bool(re.match(r"^[A-Z]{3,5}$", s)) and s not in HDR_EXCLUDE


def _row_to_pos(tokens: list[tuple[float, str]], col_x: dict[str, float]) -> Optional[dict]:
    """tokens = [(x_center, text)] terurut kiri→kanan dalam satu baris."""
    tk = next((s for _, s in tokens if _is_ticker(s)), None)
    if not tk:
        return None
    nums, pct = [], None
    for cx, s in tokens:
        if _is_ticker(s):
            continue
        if s.strip().endswith("%"):
            v = _idr(s)
            if v is not None and pct is None:
                pct = v
            continue
        v = _idr(s)
        if v is not None:
            nums.append((cx, v))
    if not nums:
        return {"ticker": tk}
    rec: dict[str, Any] = {"ticker": tk, "pl_pct": pct}
    if col_x:  # mapping berbasis header (lebih akurat)
        for cx, v in nums:
            col = min(col_x, key=lambda c: abs(col_x[c] - cx))
            if abs(col_x[col] - cx) < 120 and col not in rec:
                rec[col] = v
    else:      # fallback berbasis urutan kolom
        for k, (_, v) in zip(["lots", "avg_price", "last_price", "value", "pl"], nums):
            rec[k] = v
    return rec


def parse(file_bytes: bytes, mime_type: str, broker_hint: Optional[str] = None) -> dict[str, Any]:
    try:
        if mime_type == "application/pdf":
            data = _parse_pdf(file_bytes)
        else:
            data = _parse_image(file_bytes)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"OCR gagal: {e}"}

    broker = _norm_broker(broker_hint) or _norm_broker(data.get("broker"))

    if data.get("doc_type") == "history":
        txns = data.get("transactions") or []
        if not txns:
            return {"ok": False, "error": "Riwayat transaksi tidak terbaca. Coba gambar lebih tajam/zoom penuh."}
        return {"ok": True, "engine": "ocr", "doc_type": "history",
                "broker": broker or "Profits Anywhere", "transactions": txns,
                "catatan": f"Riwayat transaksi ({len(txns)} baris) — akan dicocokkan BUY↔JUAL utk jurnal ROI & posisi terbuka."}

    if data.get("doc_type") == "trade_confirmation":
        return _finalize_trades(data, broker)

    result = _normalize(data, broker)
    if not result["positions"]:
        return {"ok": False, "error": "OCR tidak menemukan baris saham. Coba PDF e-statement, "
                                      "gambar lebih tajam/zoom, atau isi manual."}
    result["ok"] = True
    result["engine"] = "ocr"
    if data.get("account"):
        result["account"] = data["account"]
    return result


def _ocr_data(img) -> dict:
    """Jalankan Tesseract dgn file input di direktori yang pasti terbaca.

    Beberapa lingkungan menaruh TMPDIR di lokasi yang tak bisa dibuka oleh
    biner `tesseract` (proses terpisah). Kita tulis input ke folder lokal app
    lalu beri path-nya langsung ke pytesseract, hindari temp-file bawaannya.
    """
    import os
    import tempfile

    import pytesseract

    tmpdir = os.path.join(os.path.dirname(__file__), os.pardir, "..", ".ocrtmp")
    tmpdir = os.path.abspath(tmpdir)
    os.makedirs(tmpdir, exist_ok=True)
    fd, path = tempfile.mkstemp(suffix=".png", dir=tmpdir)
    os.close(fd)
    try:
        img.save(path)
        return pytesseract.image_to_data(
            path, output_type=pytesseract.Output.DICT, config="--psm 6")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _finalize_trades(data: dict[str, Any], broker: Optional[str]) -> dict[str, Any]:
    """Susun respons utk dokumen Trade Confirmation (transaksi BELI/JUAL).

    BELI → importable sbg holding (avg = harga eksekusi). JUAL → tidak diimpor
    (harus dikurangi manual), diberi catatan.
    """
    trades = data["trades"]
    n_buy = sum(1 for t in trades if t["side"] == "BUY")
    positions = []
    for t in trades:
        is_buy = t["side"] == "BUY"
        lots = int(t["lots"]) if t.get("lots") else None
        positions.append({
            "ticker": t["ticker"], "lots": lots, "shares": t.get("shares"),
            "avg_price": t.get("avg_price"), "avg_derived": False,
            "last_price": None, "value": t.get("value"), "pl": None, "pl_pct": None,
            "side": t["side"], "company": t.get("company"), "broker": broker,
            "importable": bool(is_buy and lots and t.get("avg_price")),
        })
    note = "Dokumen ini BUKTI TRANSAKSI (Trade Confirmation), bukan laporan holdings. "
    if n_buy:
        note += f"{n_buy} transaksi BELI ditandai untuk ditambahkan. "
    if any(t["side"] == "SELL" for t in trades):
        note += "Transaksi JUAL tidak diimpor otomatis — kurangi posisi terkait manual. "
    if data.get("total_cost"):
        note += f"Total biaya (termasuk fee) Rp {int(data['total_cost']):,}".replace(",", ".")
    fee_buy = data.get("fee_buy_pct")
    account = None
    if fee_buy is not None:
        # biaya jual umumnya = biaya beli + PPh final 0.1% saat jual
        account = {"broker": broker or "Profits Anywhere",
                   "fee_buy_pct": round(fee_buy, 4), "fee_sell_pct": round(fee_buy + 0.1, 4)}
        note += f" Biaya transaksi terdeteksi: beli {fee_buy}%."
    return {
        "ok": True, "engine": "ocr", "doc_type": "trade_confirmation",
        "broker": broker, "positions": positions, "account": account,
        "total_value": None, "total_pl": None, "total_pl_pct": None,
        "catatan": note.strip(),
    }


# --- Riwayat transaksi (Order History / Mutasi) Stockbit/Bibit --- #
_TXN_ACTIONS = ("WITHDRAWAL", "WITHDRAW", "DEPOSIT", "SELL", "BUY")
_ID_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6,
              "jul": 7, "agu": 8, "agt": 8, "aug": 8, "sep": 9, "okt": 10, "oct": 10,
              "nov": 11, "des": 12, "dec": 12}


def _parse_id_date(text: str) -> Optional[tuple[str, int]]:
    """'29 Mei 2026' → ('2026-05-29', posisi_mulai)."""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})", text)
    if not m:
        return None
    mo = _ID_MONTHS.get(m.group(2)[:3].lower())
    if not mo:
        return None
    return f"{m.group(3)}-{mo:02d}-{int(m.group(1)):02d}", m.start()


def _parse_history_rows(rows: list[list[dict]]) -> list[dict]:
    """Ekstrak transaksi BUY/SELL/DEPOSIT/WITHDRAW dari baris OCR riwayat Stockbit."""
    txns = []
    for ws in rows:
        words = [w["t"] for w in ws]
        if not words:
            continue
        fw = words[0].upper().strip(":")
        action = next((a for a in _TXN_ACTIONS if fw == a or fw.startswith(a)), None)
        if not action:
            continue
        action = "WITHDRAW" if action.startswith("WITHDRAW") else action
        text = " ".join(words)
        dt = _parse_id_date(text)
        date = dt[0] if dt else None
        core = text[:dt[1]] if dt else text          # buang bagian tanggal sebelum ambil angka
        nums = [v for v in (_idr(t) for t in core.split()) if v is not None]
        if action in ("BUY", "SELL"):
            tk = next((w.upper() for w in words
                       if re.match(r"^[A-Z]{3,5}$", w.upper()) and w.upper() not in _TXN_ACTIONS), None)
            if not tk or len(nums) < 2:
                continue
            txns.append({"action": action, "ticker": tk, "lots": int(nums[0]),
                         "price": nums[1], "net": nums[-1], "date": date})
        else:
            txns.append({"action": action, "ticker": None, "lots": None,
                         "price": None, "net": (nums[-1] if nums else None), "date": date})
    return txns


def _parse_image(file_bytes: bytes) -> dict[str, Any]:
    from PIL import Image

    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
    if img.width < 1100:                       # perbesar agar OCR angka kecil lebih akurat
        scale = 1100 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    d = _ocr_data(img)

    lines: dict[tuple, list[dict]] = {}
    for i in range(len(d["text"])):
        txt = d["text"][i].strip()
        if not txt:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        lines.setdefault(key, []).append(
            {"t": txt, "x": d["left"][i], "y": d["top"][i],
             "cx": d["left"][i] + d["width"][i] / 2})
    rows = [sorted(ws, key=lambda w: w["x"]) for ws in lines.values()]
    rows.sort(key=lambda ws: ws[0]["y"])

    # Deteksi RIWAYAT TRANSAKSI (banyak baris BUY/SELL/DEPOSIT) → doc_type history
    full_low = " ".join(w["t"] for ws in rows for w in ws).lower()
    hist = _parse_history_rows(rows)
    n_trade = sum(1 for t in hist if t["action"] in ("BUY", "SELL"))
    if n_trade >= 3 or (("ordered items" in full_low or "net amount" in full_low) and n_trade >= 1):
        return {"doc_type": "history", "transactions": hist, "broker": "Stockbit/Bibit"}

    # Deteksi kolom dari SATU baris header (baris dgn kecocokan kata-kunci
    # terbanyak). Membatasi ke baris header mencegah judul/baris data
    # (mis. kata "Profits" pada judul) merebut anchor kolom secara keliru.
    def _row_cols(ws: list[dict]) -> dict[str, float]:
        cx: dict[str, float] = {}
        for w in ws:
            low = w["t"].lower().replace(".", "")
            for col, kws in COL_KEYS.items():
                if col not in cx and any(low == k.replace(" ", "") or low.startswith(k) for k in kws):
                    cx[col] = w["cx"]
        return cx

    col_x: dict[str, float] = {}
    best = 0
    for ws in rows:
        if any(_is_ticker(w["t"]) for w in ws):
            continue                       # baris data, bukan header
        cx = _row_cols(ws)
        if len(cx) > best:
            best, col_x = len(cx), cx
    if best < 2:                            # header tak jelas → fallback urutan
        col_x = {}

    positions = []
    for ws in rows:
        pos = _row_to_pos([(w["cx"], w["t"]) for w in ws], col_x)
        if pos and pos.get("ticker"):
            positions.append(pos)
    return {"positions": positions}


# Baris holding Phintraco/Profits Anywhere: "<no> <KODE> <angka...> <%>"
_PHIN_ROW = re.compile(r"^\s*\d+\s+([A-Z]{2,5})\s+([\d.,].*)$")


def _shares_to_lots(qty: Optional[float], avg: Optional[float], last: Optional[float],
                    value: Optional[float]) -> Optional[float]:
    """Tentukan LOT dari kuantitas. Phintraco memakai LEMBAR (shares); broker lain LOT.
    Verifikasi via nilai pasar: implied_shares = value/last. Jika qty≈implied → lembar."""
    if qty is None:
        return None
    implied = None
    if value and last:
        implied = value / last
    elif value and avg:
        implied = value / avg
    if implied:
        tol = max(2.0, 0.05 * implied)
        if abs(qty - implied) <= tol:           # qty = lembar → lot = qty/100
            return round(qty / 100)
        if abs(qty * 100 - implied) <= tol:     # qty = lot
            return qty
    return round(qty / 100) if qty >= 100 else qty


def _parse_phintraco(text: str) -> list[dict]:
    """Parser khusus e-statement PT Phintraco Sekuritas (Profits Anywhere).

    Kolom tetap: No | Kode | Quantity(lembar) | Avg Price | Closing Price |
    Shares Value | Market Value | Unrealized Gain/Loss | (%).
    """
    positions = []
    for ln in text.splitlines():
        m = _PHIN_ROW.match(ln)
        if not m:
            continue
        tk = m.group(1)
        if tk in HDR_EXCLUDE:
            continue
        nums, pct = [], None
        for tok in m.group(2).split():
            if tok.endswith("%"):
                v = _idr(tok)
                if v is not None and pct is None:
                    pct = v
                continue
            v = _idr(tok)
            if v is not None:
                nums.append(v)
        if len(nums) < 3:                       # minimal: qty, avg, closing
            continue
        qty, avg, last = nums[0], nums[1], nums[2]
        pl = nums[-1] if len(nums) >= 4 else None
        value = nums[-2] if len(nums) >= 5 else None     # Market Value
        lots = _shares_to_lots(qty, avg, last, value)
        positions.append({"ticker": tk, "lots": lots, "shares": qty,
                          "avg_price": avg, "last_price": last,
                          "value": value, "pl": pl, "pl_pct": pct})
    return positions


# Baris transaksi Trade Confirmation Stockbit/Bibit:
# "<ref> <board> <KODE> <nama perusahaan...> <lot> <qty> <price> <buy> <sell>"
_TC_ROW = re.compile(r"^\s*(\d{4,})\s+([A-Z]{2,3})\s+([A-Z]{3,5})\b(.*)$")


def _parse_trade_confirmation(text: str) -> dict[str, Any]:
    """Parser Trade Confirmation (bukti transaksi) Stockbit/Bibit.

    Kolom: REF# | Board | Share(kode+nama) | Lot | Quantity | Price | Buy | Sell.
    Mengembalikan transaksi dgn sisi BELI/JUAL (bukan holdings).
    """
    trades, total_cost = [], None
    for ln in text.splitlines():
        s = ln.strip()
        if s.lower().startswith("total cost"):
            tc = [_idr(t) for t in s.split() if _idr(t) is not None]
            if tc:
                total_cost = next((v for v in tc if v), tc[0])
            continue
        m = _TC_ROW.match(ln)
        if not m:
            continue
        tk = m.group(3)
        if tk in HDR_EXCLUDE:
            continue
        nums = [v for v in (_idr(t) for t in m.group(4).split()) if v is not None]
        if len(nums) < 4:                       # lot, qty, price, buy[, sell]
            continue
        lot, qty, price = nums[0], nums[1], nums[2]
        buy = nums[3] if len(nums) >= 4 else 0
        sell = nums[4] if len(nums) >= 5 else 0
        side = "SELL" if (sell and not buy) else "BUY"
        name = " ".join(t for t in m.group(4).split() if _idr(t) is None).strip()
        trades.append({"ticker": tk, "side": side, "lots": lot, "shares": qty,
                       "avg_price": price, "value": (sell or buy) or None, "company": name})
    fee_m = re.search(r"Total\s+Fee\s*:?\s*([\d.,]+)\s*%", text, re.I)
    fee_buy = _idr(fee_m.group(1)) if fee_m else None
    return {"trades": trades, "broker": "Stockbit/Bibit",
            "doc_type": "trade_confirmation", "total_cost": total_cost, "fee_buy_pct": fee_buy}


def _phintraco_account(text: str) -> Optional[dict]:
    """Ekstrak saldo cash/RDN dari e-statement Phintraco (Cash at Broker/RDN, Equity)."""
    def grab(pat: str) -> Optional[float]:
        m = re.search(pat, text, re.I)
        return _idr(m.group(1)) if m else None

    cash_broker = grab(r"Cash\s+at\s+Broker\s*:\s*([()\-\d.,]+)")
    cash_rdn = grab(r"Cash\s+at\s+RDN\s*:\s*([()\-\d.,]+)")
    equity = grab(r"Equity\s*\(\s*A\s*\+\s*B\s*\+\s*C\s*\)\s*:\s*([\d.,]+)")
    if cash_broker is None and cash_rdn is None:
        return None
    available = (cash_broker or 0) + (cash_rdn or 0)
    rdn_m = re.search(r"\bRDN\s*:\s*([A-Z0-9]{6,})", text)
    bank_m = re.search(r"\bBank\s*:\s*([A-Za-z][A-Za-z ]{1,20})", text)
    return {"broker": "Profits Anywhere", "cash": available,
            "cash_broker": cash_broker, "cash_rdn": cash_rdn, "equity": equity,
            "rdn": rdn_m.group(1) if rdn_m else None,
            "bank": bank_m.group(1).strip() if bank_m else None}


def _parse_pdf(file_bytes: bytes) -> dict[str, Any]:
    import pdfplumber

    positions = []
    pages_text = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    full = "\n".join(pages_text)
    up = full.upper()
    if "TRADE CONFIRMATION" in up or "TRADE CONFIRMATIONS" in up:
        tc = _parse_trade_confirmation(full)
        if tc["trades"]:
            return tc
    if "PHINTRACO" in up or ("AVG PRICE" in up and "CLOSING PRICE" in up):
        pos = _parse_phintraco(full)
        if pos:
            return {"positions": pos, "broker": "Profits Anywhere",
                    "account": _phintraco_account(full)}

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            for table in (page.extract_tables() or []):
                for row in table:
                    cells = [str(c or "").strip() for c in row]
                    tk = next((c for c in cells if _is_ticker(c.upper()) and _is_ticker(c.upper())), None)
                    tk = next((c.upper() for c in cells if _is_ticker(c.upper())), None)
                    if not tk:
                        continue
                    nums = [_idr(c) for c in cells if _idr(c) is not None and not _is_ticker(c.upper())]
                    rec = {"ticker": tk}
                    for k, v in zip(["lots", "avg_price", "last_price", "value", "pl"], nums):
                        rec[k] = v
                    positions.append(rec)
            if not positions:   # tak ada tabel → parse teks baris
                for ln in (page.extract_text() or "").splitlines():
                    toks = ln.split()
                    tk = next((t.upper() for t in toks if _is_ticker(t.upper())), None)
                    if not tk:
                        continue
                    nums = [_idr(t) for t in toks if _idr(t) is not None and not _is_ticker(t.upper())]
                    rec = {"ticker": tk}
                    for k, v in zip(["lots", "avg_price", "last_price", "value", "pl"], nums):
                        rec[k] = v
                    positions.append(rec)
    return {"positions": positions}
