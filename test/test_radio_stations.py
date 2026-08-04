"""Тесты CRUD радиостанций"""
import pytest
from conftest import TestingSessionLocal, register_and_login
import models


@pytest.fixture(autouse=True)
def clear_rate_limits():
    db = TestingSessionLocal()
    db.query(models.RegistrationLimit).delete()
    db.commit()
    db.close()


@pytest.fixture(autouse=True)
def clear_radio_stations():
    """Delete all radio stations between tests to avoid test ordering issues."""
    db = TestingSessionLocal()
    db.query(models.RadioStation).delete()
    db.commit()
    db.close()


def test_list_empty_catalog(client, test_user_token):
    """GET /api/radio/stations returns empty catalog."""
    r = client.get("/api/radio/stations",
                   headers={"Authorization": f"Bearer {test_user_token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["stations"] == []
    assert data["total"] == 0


def test_list_unauthenticated(client):
    """GET /api/radio/stations without token returns 401."""
    r = client.get("/api/radio/stations")
    assert r.status_code == 401


def test_create_as_admin(client, admin_token):
    """Admin can create a station."""
    r = client.post(
        "/api/radio/stations",
        json={
            "name": "Test FM",
            "stream_url": "https://test.fm/stream",
            "genre": "Pop",
            "website": "https://test.fm",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Test FM"
    assert data["stream_url"] == "https://test.fm/stream"
    assert data["genre"] == "Pop"
    assert data["website"] == "https://test.fm"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_create_as_non_admin(client, test_user_token):
    """Non-admin user cannot create a station."""
    r = client.post(
        "/api/radio/stations",
        json={
            "name": "Test FM",
            "stream_url": "https://test.fm/stream",
        },
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 403


def test_update_as_admin(client, admin_token):
    """Admin can update a station."""
    r = client.post(
        "/api/radio/stations",
        json={"name": "Old FM", "stream_url": "https://old.fm/stream"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    station_id = r.json()["id"]

    r = client.put(
        f"/api/radio/stations/{station_id}",
        json={"name": "New FM", "genre": "Rock"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "New FM"
    assert data["genre"] == "Rock"
    assert data["stream_url"] == "https://old.fm/stream"


def test_update_as_non_admin(client, test_user_token, admin_token):
    """Non-admin user cannot update a station."""
    r = client.post(
        "/api/radio/stations",
        json={"name": "Some FM", "stream_url": "https://some.fm/stream"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    station_id = r.json()["id"]

    r = client.put(
        f"/api/radio/stations/{station_id}",
        json={"name": "Hacked"},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 403


def test_update_nonexistent(client, admin_token):
    """Updating a nonexistent station returns 404."""
    r = client.put(
        "/api/radio/stations/nonexistent",
        json={"name": "Nope"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404


def test_delete_as_admin(client, admin_token):
    """Admin can delete a station."""
    r = client.post(
        "/api/radio/stations",
        json={"name": "Delete Me", "stream_url": "https://delete.me/stream"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    station_id = r.json()["id"]

    r = client.delete(
        f"/api/radio/stations/{station_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 204

    r = client.get("/api/radio/stations",
                   headers={"Authorization": f"Bearer {admin_token}"})
    assert r.json()["total"] == 0


def test_delete_as_non_admin(client, test_user_token, admin_token):
    """Non-admin user cannot delete a station."""
    r = client.post(
        "/api/radio/stations",
        json={"name": "Keep Me", "stream_url": "https://keep.me/stream"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    station_id = r.json()["id"]

    r = client.delete(
        f"/api/radio/stations/{station_id}",
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 403


def test_list_returns_all_stations(client, admin_token):
    """GET returns all stations ordered by name."""
    stations = [
        {"name": "B FM", "stream_url": "https://b.fm"},
        {"name": "A FM", "stream_url": "https://a.fm"},
        {"name": "C FM", "stream_url": "https://c.fm"},
    ]
    for s in stations:
        client.post(
            "/api/radio/stations",
            json=s,
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    r = client.get(
        "/api/radio/stations",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    names = [s["name"] for s in data["stations"]]
    assert names == ["A FM", "B FM", "C FM"]


def test_delete_nonexistent(client, admin_token):
    """Deleting a nonexistent station returns 404."""
    r = client.delete(
        "/api/radio/stations/nonexistent",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404
