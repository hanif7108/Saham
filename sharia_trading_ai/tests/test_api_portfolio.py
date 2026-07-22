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
            gold_avg_price=1200000.0,
            currency="IDR"
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
        "label": "BUY",
        "css": "buy",
        "valuation_score": 75.0,
        "timing_score": 60.0,
        "factors": [],
        "valuation_extra": {"graham_number": 6000, "margin_of_safety_pct": 33.3},
        "timing": {},
        "plan": {}
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


def test_upsert_account_with_usd():
    payload = {
        "broker": "Charles Schwab",
        "cash": 1000.0,
        "rdn": "US12345678",
        "bank": "Schwab Bank",
        "fee_buy_pct": 0.05,
        "fee_sell_pct": 0.05,
        "currency": "USD"
    }
    with patch("app.routers.accounts.accounts.set_account") as mock_set:
        mock_set.return_value = {
            "id": 2,
            "broker": "Charles Schwab",
            "cash": 1000.0,
            "currency": "USD"
        }
        
        response = client.post("/api/accounts", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["broker"] == "Charles Schwab"
        assert data["cash"] == 1000.0
        assert data["currency"] == "USD"
        mock_set.assert_called_once_with(
            "Charles Schwab",
            1000.0,
            "US12345678",
            "Schwab Bank",
            0.05,
            0.05,
            gold_balance_grams=None,
            gold_avg_price=None,
            currency="USD"
        )


def test_get_investasi_info_endpoint_with_usd_stock():
    mock_positions = {
        "positions": [
            {
                "ticker": "AAPL.US",
                "lots": 10,
                "shares": 10,  # 1 share per lot for US stock
                "avg_price": 180.0,
                "type": "investasi",
                "currency": "USD"
            }
        ],
        "investasi_summary": {
            "total_cost": 27000000,
            "total_modal": 27013500,
            "total_value": 28500000,
            "total_net_value": 28428750,
            "total_pl": 1500000,
            "total_pl_pct": 5.56,
            "jumlah_posisi": 1
        }
    }
    
    mock_eval = {
        "label": "BUY",
        "css": "buy",
        "valuation_score": 80.0,
        "timing_score": 70.0,
        "factors": []
    }
    
    mock_div = {
        "dividend_yield": 0.015,
        "upcoming": {
            "expected": True,
            "amount": 0.25, # USD 0.25 per share
            "ex_date": "2026-08-15"
        }
    }

    with patch("app.routers.portfolio.portfolio.list_positions", return_value=mock_positions), \
         patch("app.core.undervalue.evaluate", return_value=mock_eval), \
         patch("app.core.dividend.profile", return_value=mock_div), \
         patch("app.data.provider.get_usd_idr_rate", return_value=15000.0):
              
        response = client.get("/api/portfolio/investasi-info")
        
        assert response.status_code == 200
        data = response.json()
        
        # 10 shares * $0.25 * Rp15,000 = Rp37,500 expected dividend
        assert data["summary"]["total_expected_dividends"] == 37500


