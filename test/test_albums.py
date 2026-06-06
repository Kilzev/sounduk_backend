"""Тесты CRUD альбомов"""
import base64
import pytest
from conftest import TestingSessionLocal, register_and_login
import models


@pytest.fixture(autouse=True)
def clear_rate_limits():
    db = TestingSessionLocal()
    db.query(models.RegistrationLimit).delete()
    db.commit()
    db.close()


def _gen_id(suffix: str = "abc123") -> str:
    return f"1712345678901-{suffix}"


def test_get_empty_albums(client):
    token = register_and_login(client, "album_empty")
    r = client.get("/api/albums", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json() == []


def test_create_album(client):
    token = register_and_login(client, "album_creator")
    album_id = _gen_id("create")
    r = client.post(
        "/api/albums",
        json={
            "id": album_id,
            "title": "Мой альбом",
            "description": "Описание",
            "trackIds": [],
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201
    data = r.json()
    assert data["id"] == album_id
    assert data["title"] == "Мой альбом"
    assert data["description"] == "Описание"
    assert data["trackIds"] == []
    assert data["coverArt"] is None
    assert "createdAt" in data
    assert "updatedAt" in data


def test_create_album_duplicate_id(client):
    token = register_and_login(client, "album_dup")
    album_id = _gen_id("dup")
    payload = {"id": album_id, "title": "A", "trackIds": []}

    r1 = client.post("/api/albums", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r1.status_code == 201

    r2 = client.post("/api/albums", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 409


def test_create_album_empty_title(client):
    token = register_and_login(client, "album_empty_title")
    r = client.post(
        "/api/albums",
        json={"id": _gen_id("empty"), "title": "", "trackIds": []},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 422  # Pydantic validation


def test_create_album_with_cover(client):
    token = register_and_login(client, "album_cover")
    # Валидный PNG header в base64
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    cover_b64 = base64.b64encode(png_bytes).decode("ascii")

    r = client.post(
        "/api/albums",
        json={
            "id": _gen_id("cover"),
            "title": "With Cover",
            "trackIds": [],
            "coverArt": cover_b64,
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201
    assert r.json()["coverArt"] == cover_b64


def test_create_album_invalid_base64_cover(client):
    token = register_and_login(client, "album_bad_cover")
    r = client.post(
        "/api/albums",
        json={
            "id": _gen_id("bad"),
            "title": "Bad",
            "trackIds": [],
            "coverArt": "not!valid!base64!!!",
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 400


def test_update_album_title(client):
    token = register_and_login(client, "album_update_title")
    album_id = _gen_id("upd_t")
    client.post(
        "/api/albums",
        json={"id": album_id, "title": "Old", "trackIds": []},
        headers={"Authorization": f"Bearer {token}"}
    )

    r = client.put(
        f"/api/albums/{album_id}",
        json={"title": "New"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["title"] == "New"


def test_update_album_partial_keeps_other_fields(client):
    token = register_and_login(client, "album_partial")
    album_id = _gen_id("part")
    client.post(
        "/api/albums",
        json={
            "id": album_id,
            "title": "Title",
            "description": "Description",
            "trackIds": ["t1", "t2"],
        },
        headers={"Authorization": f"Bearer {token}"}
    )

    # Обновляем только trackIds
    r = client.put(
        f"/api/albums/{album_id}",
        json={"trackIds": ["t1", "t2", "t3"]},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Title"
    assert data["description"] == "Description"
    assert data["trackIds"] == ["t1", "t2", "t3"]


def test_update_album_clear_cover(client):
    token = register_and_login(client, "album_clear_cover")
    album_id = _gen_id("clr")
    cover_b64 = base64.b64encode(b"\x00" * 100).decode("ascii")
    client.post(
        "/api/albums",
        json={"id": album_id, "title": "T", "trackIds": [], "coverArt": cover_b64},
        headers={"Authorization": f"Bearer {token}"}
    )

    # Пустая строка = очистить обложку
    r = client.put(
        f"/api/albums/{album_id}",
        json={"coverArt": ""},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 200
    assert r.json()["coverArt"] is None


def test_update_nonexistent_album(client):
    token = register_and_login(client, "album_404_upd")
    r = client.put(
        f"/api/albums/{_gen_id('nope')}",
        json={"title": "X"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 404


def test_cannot_update_other_users_album(client):
    # Пользователь 1 создаёт альбом
    token_a = register_and_login(client, "album_owner_a")
    album_id = _gen_id("owner")
    client.post(
        "/api/albums",
        json={"id": album_id, "title": "A", "trackIds": []},
        headers={"Authorization": f"Bearer {token_a}"}
    )

    # Пользователь 2 пытается обновить → 404 (не раскрываем существование)
    token_b = register_and_login(client, "album_outsider_b")
    r = client.put(
        f"/api/albums/{album_id}",
        json={"title": "Hacked"},
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert r.status_code == 404


def test_delete_album(client):
    token = register_and_login(client, "album_deleter")
    album_id = _gen_id("del")
    client.post(
        "/api/albums",
        json={"id": album_id, "title": "To Delete", "trackIds": []},
        headers={"Authorization": f"Bearer {token}"}
    )

    r = client.delete(
        f"/api/albums/{album_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 204

    # Повторное удаление → 404 (идемпотентность)
    r2 = client.delete(
        f"/api/albums/{album_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r2.status_code == 404


def test_cannot_delete_other_users_album(client):
    token_a = register_and_login(client, "album_del_owner")
    album_id = _gen_id("delown")
    client.post(
        "/api/albums",
        json={"id": album_id, "title": "A", "trackIds": []},
        headers={"Authorization": f"Bearer {token_a}"}
    )

    token_b = register_and_login(client, "album_del_outsider")
    r = client.delete(
        f"/api/albums/{album_id}",
        headers={"Authorization": f"Bearer {token_b}"}
    )
    assert r.status_code == 404

    # Альбом у владельца должен остаться
    list_r = client.get("/api/albums", headers={"Authorization": f"Bearer {token_a}"})
    assert any(a["id"] == album_id for a in list_r.json())


def test_users_see_only_own_albums(client):
    token_a = register_and_login(client, "album_isolation_a")
    token_b = register_and_login(client, "album_isolation_b")

    client.post(
        "/api/albums",
        json={"id": _gen_id("isoA"), "title": "User A album", "trackIds": []},
        headers={"Authorization": f"Bearer {token_a}"}
    )
    client.post(
        "/api/albums",
        json={"id": _gen_id("isoB"), "title": "User B album", "trackIds": []},
        headers={"Authorization": f"Bearer {token_b}"}
    )

    list_a = client.get("/api/albums", headers={"Authorization": f"Bearer {token_a}"})
    list_b = client.get("/api/albums", headers={"Authorization": f"Bearer {token_b}"})

    titles_a = [a["title"] for a in list_a.json()]
    titles_b = [a["title"] for a in list_b.json()]

    assert "User A album" in titles_a
    assert "User B album" not in titles_a
    assert "User B album" in titles_b
    assert "User A album" not in titles_b


def test_update_album_flutter_like_payload(client):
    """PUT с лишними полями (id, createdAt) и кириллицей — как шлёт Flutter."""
    token = register_and_login(client, "album_flutter_put")
    album_id = _gen_id("flutter")
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    cover_b64 = base64.b64encode(png_bytes).decode("ascii")

    client.post(
        "/api/albums",
        json={"id": album_id, "title": "Old", "trackIds": []},
        headers={"Authorization": f"Bearer {token}"},
    )

    r = client.put(
        f"/api/albums/{album_id}",
        json={
            "id": album_id,
            "title": "Фанк",
            "description": None,
            "trackIds": ["track-1"],
            "createdAt": "2026-01-01T00:00:00.000Z",
            "updatedAt": "2026-06-04T10:00:00.000Z",
            "coverArt": cover_b64,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Фанк"
    assert data["trackIds"] == ["track-1"]
    assert data["coverArt"] == cover_b64


def test_isLocal_field_ignored(client):
    """Сервер должен игнорировать isLocal в body"""
    token = register_and_login(client, "album_islocal")
    album_id = _gen_id("islc")
    r = client.post(
        "/api/albums",
        json={
            "id": album_id,
            "title": "T",
            "trackIds": [],
            "isLocal": True,  # должно игнорироваться
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 201
    assert "isLocal" not in r.json()
