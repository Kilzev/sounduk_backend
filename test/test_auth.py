from fastapi.testclient import TestClient
import pytest
from conftest import TestingSessionLocal, register_and_login
import models


@pytest.fixture(autouse=True)
def clear_rate_limits():
    """Сбрасываем лимиты регистрации перед каждым тестом"""
    db = TestingSessionLocal()
    db.query(models.RegistrationLimit).delete()
    db.commit()
    db.close()


def test_register_user(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "new_user", "email": "new_user@test.com", "password": "password123"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "new_user"
    assert data["email"] == "new_user@test.com"
    assert "id" in data
    assert "storage_limit" in data
    assert "is_premium" in data
    assert data["is_verified"] is False
    # recovery_code больше не возвращается
    assert "recovery_code" not in data


def test_register_duplicate_email(client):
    client.post(
        "/api/auth/register",
        json={"username": "dup_email_1", "email": "dup@test.com", "password": "password123"}
    )
    response = client.post(
        "/api/auth/register",
        json={"username": "dup_email_2", "email": "dup@test.com", "password": "password123"}
    )
    assert response.status_code == 400
    assert "email" in response.json()["detail"].lower()


def test_login_by_email(client):
    client.post(
        "/api/auth/register",
        json={"username": "login_user", "email": "login_user@test.com", "password": "password123"}
    )
    response = client.post(
        "/api/auth/login",
        json={"email": "login_user@test.com", "password": "password123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_email(client):
    response = client.post(
        "/api/auth/login",
        json={"email": "nonexistent@test.com", "password": "password123"}
    )
    assert response.status_code == 401


def test_get_me(client):
    token = register_and_login(client, "me_user")

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "me_user"
    assert "email" in data
    assert "storage_limit" in data


def test_forgot_and_reset_password(client):
    # Регистрируемся
    client.post(
        "/api/auth/register",
        json={"username": "reset_user", "email": "reset@test.com", "password": "password123"}
    )

    # Сбрасываем code_sent_at чтобы обойти cooldown (после register)
    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.email == "reset@test.com").first()
    user.code_sent_at = None
    db.commit()
    db.close()

    # Запрашиваем сброс
    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "reset@test.com"}
    )
    assert resp.status_code == 200

    # Получаем код напрямую из БД (SMTP замокан)
    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.email == "reset@test.com").first()
    code = user.verification_code
    db.close()

    assert code is not None

    # Сбрасываем пароль
    resp = client.post(
        "/api/auth/reset-password",
        json={"email": "reset@test.com", "code": code, "new_password": "newpassword456"}
    )
    assert resp.status_code == 200

    # Логинимся новым паролем
    login = client.post(
        "/api/auth/login",
        json={"email": "reset@test.com", "password": "newpassword456"}
    )
    assert login.status_code == 200


def test_forgot_password_nonexistent_email(client):
    """Не раскрываем существование email — отвечаем 200 даже если email не найден"""
    resp = client.post(
        "/api/auth/forgot-password",
        json={"email": "nobody@test.com"}
    )
    assert resp.status_code == 200


def test_reset_password_wrong_code(client):
    client.post(
        "/api/auth/register",
        json={"username": "wrong_code_user", "email": "wrongcode@test.com", "password": "password123"}
    )

    # Сбрасываем cooldown после регистрации
    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.email == "wrongcode@test.com").first()
    user.code_sent_at = None
    db.commit()
    db.close()

    client.post(
        "/api/auth/forgot-password",
        json={"email": "wrongcode@test.com"}
    )

    resp = client.post(
        "/api/auth/reset-password",
        json={"email": "wrongcode@test.com", "code": "000000", "new_password": "newpass"}
    )
    assert resp.status_code == 400
