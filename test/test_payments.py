from fastapi.testclient import TestClient
import pytest

def test_mock_payment(client):
    # Register and login
    reg = client.post(
        "/api/auth/register",
        json={"username": "payer_old", "password": "password123"}
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "payer_old", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # Buy 5GB
    response = client.post(
        "/api/payments/mock",
        json={"product_id": "storage_pack_5gb"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_premium"] is True

def test_create_and_check_payment(client):
    # Register and login
    client.post(
        "/api/auth/register",
        json={"username": "payer_new", "password": "password123"}
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "payer_new", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # 1. Create Payment
    response = client.post(
        "/api/payments/create",
        json={"product_id": "storage_pack_3gb"},
        headers={"Authorization": f"Bearer {token}"}
    )
    # The API catches auth errors and returns mock if status 500 happens due to auth
    # Or raises 500 if not auth error.
    # If successful (mocked inside creates), we get 200
    assert response.status_code == 200
    data = response.json()
    assert "payment_id" in data
    assert "confirmation_url" in data
    payment_id = data["payment_id"]

    # 2. Check Status
    status_resp = client.get(
        f"/api/payments/{payment_id}/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    # It might be pending or succeeded depending on mock logic
    assert status_data["status"] in ["pending", "succeeded", "waiting_for_capture"]

    # 3. Simulate Webhook (or manual status update logic if mocked)
    # Since we can't easily mock webhook from external YooKassa without setting up a tunnel,
    # we rely on the check_status logic or just verify the endpoint exists.

