from fastapi.testclient import TestClient
import pytest
import io
from conftest import register_and_login


def test_upload_track(client):
    token = register_and_login(client, "uploader")

    file_content = b"\x00" * 1024
    files = {"file": ("test.mp3", io.BytesIO(file_content), "audio/mpeg")}
    data = {"title": "Test Song", "artist": "Test Artist", "duration": "180"}

    response = client.post(
        "/api/tracks/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    track_data = response.json()
    assert track_data["title"] == "Test Song"
    assert track_data["file_size"] == 1024
    assert track_data["id"]


def test_upload_requires_verification(client):
    """Неверифицированный пользователь не может загружать треки"""
    token = register_and_login(client, "unverified_uploader", verify=False)

    files = {"file": ("test.mp3", io.BytesIO(b"\x00" * 100), "audio/mpeg")}
    data = {"title": "Song", "artist": "Artist", "duration": "60"}

    response = client.post(
        "/api/tracks/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_list_tracks(client):
    token = register_and_login(client, "lister")

    file_content = b"\x00" * 1024
    files = {"file": ("test.mp3", io.BytesIO(file_content), "audio/mpeg")}
    upload_resp = client.post(
        "/api/tracks/upload",
        files=files,
        data={"title": "Track 1", "artist": "Artist 1", "duration": "120"},
        headers={"Authorization": f"Bearer {token}"}
    )
    track_id = upload_resp.json()["id"]

    response = client.get(
        "/api/tracks",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    track_ids = [t["id"] for t in data["tracks"]]
    assert track_id in track_ids


def test_delete_track(client):
    token = register_and_login(client, "deleter")

    files = {"file": ("del.mp3", io.BytesIO(b"0"), "audio/mpeg")}
    upload_resp = client.post(
        "/api/tracks/upload",
        files=files,
        data={"title": "Delete Me", "artist": "Artist", "duration": "10"},
        headers={"Authorization": f"Bearer {token}"}
    )
    track_id = upload_resp.json()["id"]

    response = client.delete(
        f"/api/tracks/{track_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204

    list_resp = client.get(
        "/api/tracks",
        headers={"Authorization": f"Bearer {token}"}
    )
    tracks = list_resp.json()["tracks"]
    assert not any(t["id"] == track_id for t in tracks)
