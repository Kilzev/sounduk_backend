from fastapi.testclient import TestClient
import pytest
import io

def test_upload_track(client):
    # Register and login
    reg = client.post(
        "/api/auth/register",
        json={"username": "uploader", "password": "password123"}
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "uploader", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # Create fake MP3 data
    file_content = b"\x00" * 1024 # 1KB dummy content
    file_obj = io.BytesIO(file_content)
    
    files = {
        "file": ("test.mp3", file_obj, "audio/mpeg")
    }
    data = {
        "title": "Test Song",
        "artist": "Test Artist",
        "duration": "180"
    }
    
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

def test_list_tracks(client):
    # Register and login
    reg = client.post(
        "/api/auth/register",
        json={"username": "lister", "password": "password123"}
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "lister", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # Upload one track
    file_content = b"\x00" * 1024
    files = {"file": ("test.mp3", io.BytesIO(file_content), "audio/mpeg")}
    upload_resp = client.post(
        "/api/tracks/upload",
        files=files,
        data={"title": "Track 1", "artist": "Artist 1", "duration": "120"},
        headers={"Authorization": f"Bearer {token}"}
    )
    track_id = upload_resp.json()["id"]
    
    # List tracks
    response = client.get(
        "/api/tracks",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    # Check if id is present in the list
    track_ids = [t["id"] for t in data["tracks"]]
    assert track_id in track_ids

def test_delete_track(client):
    # Register, login, upload
    reg = client.post(
        "/api/auth/register",
        json={"username": "deleter", "password": "password123"}
    )
    login = client.post(
        "/api/auth/login",
        json={"username": "deleter", "password": "password123"}
    )
    token = login.json()["access_token"]
    
    # Upload
    files = {"file": ("del.mp3", io.BytesIO(b"0"), "audio/mpeg")}
    upload_resp = client.post(
        "/api/tracks/upload",
        files=files,
        data={"title": "Delete Me", "artist": "Artist", "duration": "10"},
        headers={"Authorization": f"Bearer {token}"}
    )
    track_id = upload_resp.json()["id"]
    
    # Delete
    response = client.delete(
        f"/api/tracks/{track_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 204
    
    # Verify gone
    list_resp = client.get(
        "/api/tracks",
        headers={"Authorization": f"Bearer {token}"}
    )
    tracks = list_resp.json()["tracks"]
    assert not any(t["id"] == track_id for t in tracks)
