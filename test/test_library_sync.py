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


def test_get_tracks_default_limit_and_cursor(client):
    """GET /api/tracks pages newest-first (default limit=30)."""
    token = register_and_login(client, "lib_page_tracks")
    headers = _auth(token)

    for i in range(35):
        mp3_header = b"ID3" + b"\x00" * 100
        files = {"file": (f"t{i}.mp3", io.BytesIO(mp3_header), "audio/mpeg")}
        data = {
            "title": f"Paged {i}",
            "artist": "Pager",
            "duration": "10",
        }
        r = client.post("/api/tracks/upload", files=files, data=data, headers=headers)
        assert r.status_code in (200, 201), r.text

    r = client.get("/api/tracks", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 35
    assert len(body["tracks"]) == 30
    assert body["has_more"] is True
    assert body.get("next_cursor")

    first_ids = [t["id"] for t in body["tracks"]]
    first_dates = [t["created_at"] for t in body["tracks"]]
    assert first_dates == sorted(first_dates, reverse=True)

    r2 = client.get(
        "/api/tracks",
        params={"cursor": body["next_cursor"], "limit": 30},
        headers=headers,
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert len(body2["tracks"]) >= 5
    second_ids = [t["id"] for t in body2["tracks"]]
    assert set(first_ids).isdisjoint(second_ids)
    # Page 2 is older than (or equal, then lower id) the last row of page 1.
    assert body2["tracks"][0]["created_at"] <= first_dates[-1]
    ids = set(first_ids) | set(second_ids)
    assert len(ids) >= 35


def test_get_tracks_first_page_is_newest(client):
    token = register_and_login(client, "lib_newest_first")
    headers = _auth(token)
    for i, title in enumerate(("oldest", "middle", "newest"), start=1):
        files = {
            "file": (f"{title}.mp3", io.BytesIO(b"ID3" + b"\x00" * 100), "audio/mpeg")
        }
        data = {
            "title": title,
            "artist": "Ord",
            "duration": "10",
            "created_at": f"2026-01-0{i}T12:00:00",
        }
        r = client.post("/api/tracks/upload", files=files, data=data, headers=headers)
        assert r.status_code in (200, 201), r.text

    r = client.get("/api/tracks", params={"limit": 1}, headers=headers)
    assert r.status_code == 200
    assert r.json()["tracks"][0]["title"] == "newest"

    r2 = client.get(
        "/api/tracks",
        params={"limit": 1, "cursor": r.json()["next_cursor"]},
        headers=headers,
    )
    assert r2.status_code == 200
    assert r2.json()["tracks"][0]["title"] == "middle"
