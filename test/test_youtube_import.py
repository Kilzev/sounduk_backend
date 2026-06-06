import httpx

from api.tracks import (
    _extract_playlist_video_ids_from_html,
    _is_youtube_watch_url,
    _parse_youtube_mp3_response,
    _parse_youtube_url_parts,
    _title_artist_from_youtube_title,
    _youtube_audio_provider,
    _youtube_mp3_endpoint,
)


def test_parse_youtube_video_url():
    video_id, list_id = _parse_youtube_url_parts("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert video_id == "dQw4w9WgXcQ"
    assert list_id is None


def test_parse_youtube_playlist_url():
    video_id, list_id = _parse_youtube_url_parts(
        "https://www.youtube.com/playlist?list=PLtest123456789"
    )
    assert video_id is None
    assert list_id == "PLtest123456789"


def test_parse_youtube_video_in_playlist_url():
    video_id, list_id = _parse_youtube_url_parts(
        "https://www.youtube.com/watch?v=abc12345678&list=PLalbum999"
    )
    assert video_id == "abc12345678"
    assert list_id == "PLalbum999"


def test_is_youtube_watch_url():
    assert _is_youtube_watch_url("https://youtu.be/dQw4w9WgXcQ")
    assert not _is_youtube_watch_url("https://example.com/watch?v=dQw4w9WgXcQ")


def test_extract_playlist_video_ids_from_html():
    html = """
    "videoId":"aaaaaaaaaaa"
    "videoId":"bbbbbbbbbbb"
    "videoId":"aaaaaaaaaaa"
    """
    assert _extract_playlist_video_ids_from_html(html) == ["aaaaaaaaaaa", "bbbbbbbbbbb"]


def test_title_artist_from_youtube_title():
    assert _title_artist_from_youtube_title("Artist Name - Song Title") == (
        "Song Title",
        "Artist Name",
    )


def test_youtube_audio_provider_default(monkeypatch):
    monkeypatch.delenv("YOUTUBE_AUDIO_PROVIDER", raising=False)
    assert _youtube_audio_provider() == "ytdlp"


def test_youtube_mp3_endpoint_defaults():
    host, path = _youtube_mp3_endpoint()
    assert host == "youtube-mp310.p.rapidapi.com"
    assert path == "/download/mp3"


def test_parse_youtube_mp3_plain_text_url():
    response = httpx.Response(
        200,
        text="https://cdn.example.com/track.mp3\n",
        headers={"content-type": "text/plain"},
    )
    assert _parse_youtube_mp3_response(response) == "https://cdn.example.com/track.mp3"


def test_parse_youtube_mp3_json_file_field():
    response = httpx.Response(
        200,
        json={"status": "success", "file": "https://cdn.example.com/from-json.mp3"},
    )
    assert _parse_youtube_mp3_response(response) == "https://cdn.example.com/from-json.mp3"
