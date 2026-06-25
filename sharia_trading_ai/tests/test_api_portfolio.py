from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_sync_portfolio_endpoint():
    payload = [
        {"ticker": "ANTM", "lots": 10, "avg_price": 1500.0, "broker": "Profits Anywhere"},
        {"ticker": "PTBA", "lots": 5, "avg_price": 2500.0, "broker": "Profits Anywhere"}
    ]
    with patch("app.routers.portfolio.portfolio.sync_broker_positions") as mock_sync:
        mock_sync.return_value = ["ANTM", "PTBA"]
        
        response = client.post("/api/portfolio/sync?broker=Profits Anywhere", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["broker"] == "Profits Anywhere"
        assert data["imported"] == ["ANTM", "PTBA"]
        mock_sync.assert_called_once_with(
            "Profits Anywhere",
            [
                {"ticker": "ANTM", "lots": 10, "avg_price": 1500.0, "broker": "Profits Anywhere", "type": "trading", "importable": True},
                {"ticker": "PTBA", "lots": 5, "avg_price": 2500.0, "broker": "Profits Anywhere", "type": "trading", "importable": True}
            ]
        )


def test_upsert_account_with_gold():
    payload = {
        "broker": "Profits Anywhere",
        "cash": 2586886.0,
        "rdn": "AT00136MI00193",
        "bank": "BCA",
        "fee_buy_pct": 0.15,
        "fee_sell_pct": 0.25,
        "gold_balance_grams": 5.0,
        "gold_avg_price": 1200000.0
    }
    with patch("app.routers.accounts.accounts.set_account") as mock_set:
        mock_set.return_value = {
            "id": 1,
            "broker": "Profits Anywhere",
            "cash": 2586886.0,
            "gold_balance_grams": 5.0,
            "gold_avg_price": 1200000.0
        }
        
        response = client.post("/api/accounts", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["broker"] == "Profits Anywhere"
        assert data["gold_balance_grams"] == 5.0
        assert data["gold_avg_price"] == 1200000.0
        mock_set.assert_called_once_with(
            "Profits Anywhere",
            2586886.0,
            "AT00136MI00193",
            "BCA",
            0.15,
            0.25,
            gold_balance_grams=5.0,
            gold_avg_price=1200000.0
        )


def test_get_investasi_info_endpoint():
    mock_positions = {
        "positions": [
            {
                "ticker": "ASII",
                "lots": 10,
                "shares": 1000,
                "avg_price": 4500.0,
                "type": "investasi"
            }
        ],
        "investasi_summary": {
            "total_cost": 4500000,
            "total_modal": 4506750,
            "total_value": 4700000,
            "total_net_value": 4688250,
            "total_pl": 200000,
            "total_pl_pct": 4.44,
            "jumlah_posisi": 1
        }
    }
    
    mock_eval = {
        "verdict": "BUY",
        "verdict_class": "buy",
        "val_score": 75.0,
        "technical_score": 60.0,
        "factors": [],
        "extra": {"graham_number": 6000, "margin_of_safety_pct": 33.3},
        "technical": {},
        "trade_plan": {}
    }
    
    mock_div = {
        "dividend_yield": 0.08,
        "pay_streak": 5,
        "years_paid": 5,
        "upcoming": {
            "expected": True,
            "amount": 100.0,
            "ex_date": "2026-07-10",
            "days_until": 15,
            "event_yield_pct": 2.2,
            "source": "yfinance"
        }
    }

    with patch("app.routers.portfolio.portfolio.list_positions", return_value=mock_positions), \
         patch("app.core.undervalue.evaluate", return_value=mock_eval), \
         patch("app.core.dividend.profile", return_value=mock_div):
             
        response = client.get("/api/portfolio/investasi-info")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "positions" in data
        assert len(data["positions"]) == 1
        assert data["positions"][0]["ticker"] == "ASII"
        
        assert "summary" in data
        assert data["summary"]["total_expected_dividends"] == 100000
        
        assert "recommendations" in data
        tickers_in_recs = [r["ticker"] for r in data["recommendations"]]
        assert "ASII" in tickers_in_recs
        assert "SIDO" in tickers_in_recs


