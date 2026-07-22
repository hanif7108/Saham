"""Tes aturan venue US=Pluang & alokasi mengikuti portofolio."""

from app.core import decisions as dec


def test_broker_matches_us_only_pluang():
    assert dec.broker_matches_ticker("Pluang", "AAPL.US") is True
    assert dec.broker_matches_ticker("Pluang", "AAPL") is True
    assert dec.broker_matches_ticker("Profits Anywhere", "AAPL.US") is False
    assert dec.broker_matches_ticker("Profits Anywhere", "BBCA") is True
    assert dec.broker_matches_ticker("Pluang", "BBCA") is False
    assert dec.broker_matches_ticker("Tring Pegadaian", "BBCA") is False


def test_venue_for_ticker():
    assert dec.venue_for_ticker("NVDA.US") == "Pluang"
    assert dec.venue_for_ticker("TLKM") == "RDN BEI"


def test_alloc_buy_us_requires_pluang():
    out = dec._alloc_buy(
        "AAPL.US",
        price=180.0,
        pos_by_tk={},
        rdn_list=[{
            "broker": "Profits Anywhere",
            "cash": 10_000_000,
            "fee_buy_pct": 0.15,
            "fee_sell_pct": 0.25,
            "advice": {"open_slots": 2, "per_emiten": 3_000_000, "risk_pct": 3, "profit_pct": 6},
        }],
    )
    assert out["lots"] == 0
    assert out["rdn"] == "Pluang"
    assert "Pluang" in out["catatan"]


def test_alloc_buy_us_on_pluang_uses_shares():
    out = dec._alloc_buy(
        "AAPL.US",
        price=100.0,
        pos_by_tk={},
        rdn_list=[{
            "broker": "Pluang",
            "cash": 1000.0,
            "currency": "USD",
            "fee_buy_pct": 0.0,
            "fee_sell_pct": 0.0,
            "advice": {"open_slots": 2, "per_emiten": 500.0, "risk_pct": 3, "profit_pct": 6},
        }],
    )
    assert out["rdn"] == "Pluang"
    assert out["currency"] == "USD"
    assert out["shares_per_lot"] == 1
    assert out["lots"] == 5  # 500 / 100
    assert out["sesuai_portofolio"] is True


def test_alloc_buy_idx_uses_lot_100():
    out = dec._alloc_buy(
        "BBCA",
        price=10000.0,
        pos_by_tk={},
        rdn_list=[{
            "broker": "Profits Anywhere",
            "cash": 5_000_000,
            "fee_buy_pct": 0.0,
            "fee_sell_pct": 0.0,
            "advice": {"open_slots": 1, "per_emiten": 2_000_000, "risk_pct": 3, "profit_pct": 6},
        }],
    )
    # 2_000_000 / (10000*100) = 2 lot
    assert out["lots"] == 2
    assert out["shares_per_lot"] == 100
    assert out["rdn"] == "Profits Anywhere"


def test_enrich_sell_without_position_becomes_hold():
    recs = [{"ticker": "ZZZZ", "action": "SELL", "reason": "test", "context": "PORTFOLIO"}]
    dec._enrich(recs, {}, [])
    assert recs[0]["action"] == "HOLD"
    assert recs[0]["context"] == "SKIP_NO_POSITION"


def test_enrich_sell_uses_portfolio_lots():
    pos = {
        "ticker": "ANTM",
        "broker": "Profits Anywhere",
        "lots": 12,
        "avg_price": 1500,
        "current_price": 1600,
        "value": 1_920_000,
        "net_value": 1_900_000,
        "currency": "IDR",
    }
    recs = [{"ticker": "ANTM", "action": "SELL", "reason": "CUT LOSS — P/L -8%", "context": "PORTFOLIO"}]
    dec._enrich(recs, {"ANTM": pos}, [])
    assert recs[0]["action"] == "SELL"
    assert recs[0]["alokasi"]["lots"] == 12
    assert recs[0]["alokasi"]["sesuai_portofolio"] is True
    assert recs[0]["exit_plan"]["lots_total"] == 12
