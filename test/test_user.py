from fastapi.testclient import TestClient
import pytest
from conftest import register_and_login


def test_delete_user(client):
    token = register_and_login(client, "delete_me")

    response = client.delete(
        "/api/users/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204


def test_update_user(client):
    token = register_and_login(client, "update_me")

    response = client.patch(
        "/api/users/me",
        json={"username": "updated_user"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["username"] == "updated_user"


def test_storage_usage(client):
    token = register_and_login(client, "storage_user")

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
    token = register_and_login(client, "storage_contract_user")

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
