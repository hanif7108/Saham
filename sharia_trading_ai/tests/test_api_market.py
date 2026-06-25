from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_market_endpoint_returns_now_wib():
    response = client.get("/api/market")
    assert response.status_code == 200
    data = response.json()
    if data.get("ok"):
        assert "now_wib" in data
        assert "WIB" in data["now_wib"]
        assert len(data["now_wib"]) > 0
