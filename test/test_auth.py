from fastapi.testclient import TestClient
import pytest

def test_register_user(client):
    response = client.post(
        "/api/auth/register",
        json={"username": "new_user", "password": "password123"}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "new_user"
    assert "id" in data
    assert "storage_limit" in data
    assert "is_premium" in data
    assert "recovery_code" in data

def test_login_user(client):
    # Register first
    client.post(
        "/api/auth/register",
        json={"username": "login_user", "password": "password123"}
    )
    # Login
    response = client.post(
        "/api/auth/login",
        json={"username": "login_user", "password": "password123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_get_me(client):
    # User token
    reg = client.post(
        "/api/auth/register",
        json={"username": "me_user", "password": "password123"}
    )
    # Login to get token
    login = client.post(
        "/api/auth/login",
        json={"username": "me_user", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "me_user"
    assert "storage_limit" in data

def test_recover_password(client):
    # Register
    reg = client.post(
        "/api/auth/register",
        json={"username": "recover_user", "password": "password123"}
    )
    recovery_code = reg.json()["recovery_code"]
    
    # Recover
    response = client.post(
        "/api/auth/recover",
        json={
            "username": "recover_user", 
            "recovery_code": recovery_code,
            "new_password": "newpassword123"
        }
    )
    assert response.status_code == 200
    assert "new_recovery_code" in response.json()
    
    # Login with new password
    login = client.post(
        "/api/auth/login",
        json={"username": "recover_user", "password": "newpassword123"}
    )
    assert login.status_code == 200
