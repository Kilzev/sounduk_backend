"""YouTube / link import gated by allow_youtube_import (not Premium)."""
from conftest import TestingSessionLocal, register_and_login
import models


def _set_flags(username: str, *, allow_youtube: bool = False, premium: bool = False):
    db = TestingSessionLocal()
    user = db.query(models.User).filter(models.User.username == username).first()
    user.allow_youtube_import = allow_youtube
    user.is_premium = premium
    db.commit()
    db.close()


def test_youtube_import_forbidden_without_flag(client):
    token = register_and_login(client, "yt_no_flag")
    _set_flags("yt_no_flag", allow_youtube=False, premium=True)

    response = client.post(
        "/api/tracks/import/youtube/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    assert response.status_code == 403
    assert "недоступен" in response.json()["detail"].lower()


def test_youtube_import_allowed_with_flag_without_premium(client):
    token = register_and_login(client, "yt_with_flag")
    _set_flags("yt_with_flag", allow_youtube=True, premium=False)

    response = client.post(
        "/api/tracks/import/youtube/jobs",
        headers={"Authorization": f"Bearer {token}"},
        json={"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    # Flag passes auth; may still fail validation / worker — but not 403 flag gate
    assert response.status_code != 403
