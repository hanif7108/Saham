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
                {"ticker": "ANTM", "lots": 10, "avg_price": 1500.0, "broker": "Profits Anywhere", "importable": True},
                {"ticker": "PTBA", "lots": 5, "avg_price": 2500.0, "broker": "Profits Anywhere", "importable": True}
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

