"""Тесты пользовательских радиостанций (привязка к аккаунту)."""
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
def clear_user_radio_stations():
    db = TestingSessionLocal()
    db.query(models.UserRadioStation).delete()
    db.commit()
    db.close()


def test_list_empty(client, test_user_token):
    r = client.get(
        "/api/users/radio/stations",
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 200
    assert r.json()["stations"] == []
    assert r.json()["total"] == 0


def test_list_unauthenticated(client):
    r = client.get("/api/users/radio/stations")
    assert r.status_code == 401


def test_create_and_list(client, test_user_token):
    r = client.post(
        "/api/users/radio/stations",
        json={"name": "My FM", "stream_url": "https://my.fm/stream"},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "My FM"
    assert data["stream_url"] == "https://my.fm/stream"
    assert "id" in data

    r = client.get(
        "/api/users/radio/stations",
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1


def test_replace_stations(client, test_user_token):
    r = client.put(
        "/api/users/radio/stations",
        json={
            "stations": [
                {"id": "a1", "name": "A FM", "stream_url": "https://a.fm"},
                {"name": "B FM", "stream_url": "https://b.fm"},
            ]
        },
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    names = {s["name"] for s in data["stations"]}
    assert names == {"A FM", "B FM"}
    ids = {s["id"] for s in data["stations"]}
    assert "a1" in ids

    # Replace again — old gone
    r = client.put(
        "/api/users/radio/stations",
        json={"stations": [{"name": "Only", "stream_url": "https://only.fm"}]},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["stations"][0]["name"] == "Only"


def test_free_limit_on_replace(client, test_user_token):
    stations = [
        {"name": f"S{i}", "stream_url": f"https://s{i}.fm"}
        for i in range(6)
    ]
    r = client.put(
        "/api/users/radio/stations",
        json={"stations": stations},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 400


def test_premium_unlimited(client, test_user_token):
    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.username == "test_user").first()
    assert user is not None
    user.is_premium = True
    db.commit()
    db.close()

    stations = [
        {"name": f"S{i}", "stream_url": f"https://s{i}.fm"}
        for i in range(8)
    ]
    r = client.put(
        "/api/users/radio/stations",
        json={"stations": stations},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 8


def test_delete_station(client, test_user_token):
    r = client.post(
        "/api/users/radio/stations",
        json={"name": "Del", "stream_url": "https://del.fm"},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    station_id = r.json()["id"]

    r = client.delete(
        f"/api/users/radio/stations/{station_id}",
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 204

    r = client.get(
        "/api/users/radio/stations",
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.json()["total"] == 0


def test_stations_isolated_per_user(client, test_user_token):
    client.post(
        "/api/users/radio/stations",
        json={"name": "User1 FM", "stream_url": "https://u1.fm"},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )

    token2 = register_and_login(client, "other_user", "pass12345")
    r = client.get(
        "/api/users/radio/stations",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert r.json()["total"] == 0


def test_cascade_on_user_delete(client, admin_token):
    token = register_and_login(client, "cascade_radio_user", "pass12345")
    client.put(
        "/api/users/radio/stations",
        json={"stations": [{"name": "Gone", "stream_url": "https://gone.fm"}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.username == "cascade_radio_user").first()
    user_id = user.id
    assert db.query(models.UserRadioStation).filter_by(user_id=user_id).count() == 1
    db.close()

    r = client.delete(
        f"/api/admin/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 204

    db = TestingSessionLocal()
    assert db.query(models.UserRadioStation).filter_by(user_id=user_id).count() == 0
    db.close()


_TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def test_user_station_cover_put_by_id(client, test_user_token, mock_s3_covers):
    r = client.post(
        "/api/users/radio/stations",
        json={
            "name": "My Cover FM",
            "stream_url": "https://mycover.fm/stream",
            "cover_data": _TINY_PNG_B64,
        },
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    station_id = data["id"]
    assert data["cover_url"]
    assert "/radio_covers/" in data["cover_url"]

    r = client.put(
        f"/api/users/radio/stations/{station_id}",
        json={"name": "Renamed FM"},
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed FM"
    assert r.json()["cover_url"]

    token2 = register_and_login(client, "cover_other_user", "pass12345")
    r = client.put(
        f"/api/users/radio/stations/{station_id}",
        json={"clear_cover": True},
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert r.status_code == 404


def test_bulk_put_preserves_cover_path(client, test_user_token, mock_s3_covers):
    r = client.post(
        "/api/users/radio/stations",
        json={
            "name": "Keep Cover",
            "stream_url": "https://keepcover.fm",
            "cover_data": _TINY_PNG_B64,
        },
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 201, r.text
    station_id = r.json()["id"]
    old_cover = r.json()["cover_url"]

    r = client.put(
        "/api/users/radio/stations",
        json={
            "stations": [
                {
                    "id": station_id,
                    "name": "Keep Cover",
                    "stream_url": "https://keepcover.fm",
                }
            ]
        },
        headers={"Authorization": f"Bearer {test_user_token}"},
    )
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["stations"][0]["cover_url"] == old_cover
