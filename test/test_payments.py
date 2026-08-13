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


def test_create_and_check_payment(client, monkeypatch):
    # Geo off by default / explicit — TestClient has private IP.
    monkeypatch.delenv("PAYMENTS_GEO_ENFORCE", raising=False)
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


def test_eligibility_allowed_when_geo_off(client, monkeypatch):
    monkeypatch.delenv("PAYMENTS_GEO_ENFORCE", raising=False)
    token = register_and_login(client, "elig_off")
    response = client.get(
        "/api/payments/eligibility",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is True
    assert data["message_key"] == "payment_region_ok"


def test_eligibility_ru_when_enforced(client, monkeypatch):
    monkeypatch.setenv("PAYMENTS_GEO_ENFORCE", "true")
    monkeypatch.setenv("PAYMENTS_ALLOWED_COUNTRIES", "RU")
    monkeypatch.setenv("PAYMENTS_GEO_FORCE_COUNTRY", "RU")
    token = register_and_login(client, "elig_ru")
    response = client.get(
        "/api/payments/eligibility",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["allowed"] is True
    assert data["country"] == "RU"
    assert data["message_key"] == "payment_region_ok"


def test_create_denied_outside_ru(client, monkeypatch):
    monkeypatch.setenv("PAYMENTS_GEO_ENFORCE", "true")
    monkeypatch.setenv("PAYMENTS_ALLOWED_COUNTRIES", "RU")
    monkeypatch.setenv("PAYMENTS_GEO_FORCE_COUNTRY", "US")
    token = register_and_login(client, "payer_us")

    with patch("api.payments.Payment.create") as create_mock:
        response = client.post(
            "/api/payments/create",
            json={"product_id": "storage_pack_3gb"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "payment_region_unavailable"
        create_mock.assert_not_called()


def test_create_allowed_for_ru_when_enforced(client, monkeypatch):
    monkeypatch.setenv("PAYMENTS_GEO_ENFORCE", "true")
    monkeypatch.setenv("PAYMENTS_ALLOWED_COUNTRIES", "RU")
    monkeypatch.setenv("PAYMENTS_GEO_FORCE_COUNTRY", "RU")
    token = register_and_login(client, "payer_ru")

    fake_payment = SimpleNamespace(
        id="pay_ru_ok",
        status="pending",
        confirmation=SimpleNamespace(
            confirmation_url="https://yoomoney.ru/checkout/payments/v2/contract?orderId=pay_ru_ok"
        ),
    )
    with patch("api.payments.Payment.create", return_value=fake_payment):
        response = client.post(
            "/api/payments/create",
            json={"product_id": "storage_pack_5gb"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    assert response.json()["payment_id"] == "pay_ru_ok"
