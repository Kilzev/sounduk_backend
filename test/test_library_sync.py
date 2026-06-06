"""Тесты library_revision и conditional sync."""
import io

from conftest import register_and_login


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_library_revision_after_register(client):
    token = register_and_login(client, "lib_rev_register")
    r = client.get("/api/users/library-revision", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["revision"] == 1


def test_create_album_bumps_revision(client):
    token = register_and_login(client, "lib_rev_album")
    before = client.get("/api/users/library-revision", headers=_auth(token)).json()["revision"]

    r = client.post(
        "/api/albums",
        json={"id": "1712345678901-rev", "title": "Rev Album", "trackIds": []},
        headers=_auth(token),
    )
    assert r.status_code == 201

    after = client.get("/api/users/library-revision", headers=_auth(token)).json()["revision"]
    assert after == before + 1


def test_get_tracks_unchanged_with_since_revision(client):
    token = register_and_login(client, "lib_rev_tracks")
    rev = client.get("/api/users/library-revision", headers=_auth(token)).json()["revision"]

    r = client.get(
        f"/api/tracks?since_revision={rev}",
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["unchanged"] is True
    assert data["revision"] == rev
    assert data["tracks"] == []
    assert data["total"] == 0
    assert r.headers.get("X-Library-Revision") == str(rev)


def test_get_albums_unchanged_with_since_revision(client):
    token = register_and_login(client, "lib_rev_albums")
    rev = client.get("/api/users/library-revision", headers=_auth(token)).json()["revision"]

    r = client.get(
        f"/api/albums?since_revision={rev}",
        headers=_auth(token),
    )
    assert r.status_code == 200
    data = r.json()
    assert data["unchanged"] is True
    assert data["revision"] == rev
    assert data["albums"] == []
    assert r.headers.get("X-Library-Revision") == str(rev)


def test_get_albums_legacy_list_format_without_since_revision(client):
    token = register_and_login(client, "lib_rev_legacy")
    r = client.get("/api/albums", headers=_auth(token))
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert r.headers.get("X-Library-Revision") == "1"


def test_upload_track_bumps_revision(client):
    token = register_and_login(client, "lib_rev_upload")
    before = client.get("/api/users/library-revision", headers=_auth(token)).json()["revision"]

    mp3_header = b"ID3" + b"\x00" * 100
    files = {"file": ("test.mp3", io.BytesIO(mp3_header), "audio/mpeg")}
    data = {
        "title": "Rev Track",
        "artist": "Artist",
        "duration": "120",
    }
    r = client.post(
        "/api/tracks/upload",
        files=files,
        data=data,
        headers=_auth(token),
    )
    assert r.status_code == 201

    after = client.get("/api/users/library-revision", headers=_auth(token)).json()["revision"]
    assert after == before + 1

    tracks = client.get("/api/tracks", headers=_auth(token))
    assert tracks.status_code == 200
    assert tracks.headers.get("X-Library-Revision") == str(after)
    assert tracks.json()["total"] == 1
