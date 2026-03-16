from fastapi.testclient import TestClient
import pytest

def test_delete_user(client):
    # Register and delete
    reg = client.post(
        "/api/auth/register",
        json={"username": "delete_me", "password": "password123"}
    )
    # Login
    login = client.post(
        "/api/auth/login",
        json={"username": "delete_me", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # Delete
    response = client.delete(
        "/api/users/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204

def test_update_user(client):
    # Register
    reg = client.post(
        "/api/auth/register",
        json={"username": "update_me", "password": "password123"}
    )
    # Login
    login = client.post(
        "/api/auth/login",
        json={"username": "update_me", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # Update username
    response = client.patch(
        "/api/users/me",
        json={"username": "updated_user"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "updated_user"

def test_storage_usage(client):
    # Register
    reg = client.post(
        "/api/auth/register",
        json={"username": "storage_user", "password": "password123"}
    )
    # Login
    login = client.post(
        "/api/auth/login",
        json={"username": "storage_user", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # Get storage usage (initially 0)
    response = client.get(
        "/api/users/storage/usage",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["storage_used"] == 0
    assert data["percentage"] == 0.0
    assert data["storage_limit"] > 0

def test_storage_stats_contract(client):
    client.post(
        "/api/auth/register",
        json={"username": "storage_contract_user", "password": "password123"}
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "storage_contract_user", "password": "password123"}
    )
    token = login.json()["access_token"]

    response = client.get(
        "/api/users/storage",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200

    data = response.json()
    assert set(data.keys()) == {"used_space", "storage_limit", "used_percentage"}
    assert isinstance(data["used_space"], int)
    assert isinstance(data["storage_limit"], int)
    assert isinstance(data["used_percentage"], float)
    assert data["used_space"] == 0
    assert data["used_percentage"] == 0.0
