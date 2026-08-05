from types import SimpleNamespace
from unittest.mock import patch

from conftest import register_and_login


def test_mock_payment_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("ENABLE_PAYMENT_MOCK", raising=False)
    token = register_and_login(client, "payer_mock_off")

    response = client.post(
        "/api/payments/mock",
        json={"product_id": "storage_pack_5gb"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_mock_payment(client, monkeypatch):
    monkeypatch.setenv("ENABLE_PAYMENT_MOCK", "true")
    token = register_and_login(client, "payer_old")

    response = client.post(
        "/api/payments/mock",
        json={"product_id": "storage_pack_5gb"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_premium"] is True


def test_create_and_check_payment(client):
    token = register_and_login(client, "payer_new")

    fake_payment = SimpleNamespace(
        id="pay_test_123",
        status="pending",
        confirmation=SimpleNamespace(
            confirmation_url="https://yoomoney.ru/checkout/payments/v2/contract?orderId=pay_test_123"
        ),
    )
    fake_status = SimpleNamespace(status="pending")

    with (
        patch("api.payments.Payment.create", return_value=fake_payment),
        patch("api.payments.Payment.find_one", return_value=fake_status),
    ):
        response = client.post(
            "/api/payments/create",
            json={"product_id": "storage_pack_3gb"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "payment_id" in data
        assert "confirmation_url" in data
        payment_id = data["payment_id"]

        status_resp = client.get(
            f"/api/payments/{payment_id}/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["status"] in [
            "pending",
            "succeeded",
            "waiting_for_capture",
        ]
