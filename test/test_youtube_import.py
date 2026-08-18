from fastapi import HTTPException

from api.tracks import (
    _classify_youtube_import_error,
    _extract_playlist_video_ids_from_html,
    _format_import_job_error,
    _humanize_youtube_import_error,
    _is_non_retryable_import_error,
    _is_youtube_watch_url,
    _parse_youtube_url_parts,
    _title_artist_from_youtube_title,
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
        None,
    )


def test_title_artist_from_youtube_topic_album_suffix():
    assert _title_artist_from_youtube_title(
        "Don't Stay - Linkin Park (Meteora)"
    ) == ("Don't Stay", "Linkin Park", "Meteora")
    assert _title_artist_from_youtube_title(
        "Hit The Floor - Linkin Park (Meteora)"
    ) == ("Hit The Floor", "Linkin Park", "Meteora")
    assert _title_artist_from_youtube_title(
        "Foreword - Linkin Park (Meteora)"
    ) == ("Foreword", "Linkin Park", "Meteora")


def test_title_artist_official_video_keeps_title():
    assert _title_artist_from_youtube_title(
        "Faint (Official HD Music Video) - Linkin Park"
    )[0].startswith("Faint")
    title, artist, album = _title_artist_from_youtube_title(
        "Somewhere I Belong (Official Music Video)"
    )
    assert title.startswith("Somewhere I Belong")
    assert album is None


def test_title_artist_uses_channel_hint_not_longer_right_side():
    title, artist, album = _title_artist_from_youtube_title(
        "Faint - Linkin Park (Meteora)",
        hint_artist="Linkin Park",
    )
    assert title == "Faint"
    assert artist == "Linkin Park"
    assert album == "Meteora"


def test_classify_geo_without_video_unavailable_prefix():
    msg = (
        "ERROR: [youtube] NR57D2UVqm4: This content is not available on this "
        "country domain due to a legal complaint from the government."
    )
    assert _classify_youtube_import_error(msg) == "geo"
    assert _is_non_retryable_import_error(msg) is True
    assert "регионе" in _humanize_youtube_import_error(msg)


def test_classify_copyright_claimed_content():
    msg = (
        "ERROR: [youtube] XOJcOXLD9ts: Video unavailable. "
        "It was blocked due to the claimed content by WMG."
    )
    assert _classify_youtube_import_error(msg) == "copyright"
    assert _is_non_retryable_import_error(msg) is True
    assert "правообладателем" in _humanize_youtube_import_error(msg)


def test_format_import_job_error_humanizes_http_detail():
    exc = HTTPException(
        status_code=502,
        detail=(
            "Не удалось скачать аудио с YouTube (yt-dlp): "
            "ERROR: [youtube] unrs1wnz0r4: Video unavailable. "
            "This content is not available on this country domain "
            "due to a legal complaint from the government."
        ),
    )
    assert _format_import_job_error(exc) == _humanize_youtube_import_error(exc.detail)


def test_transient_ytdlp_error_is_retryable():
    msg = "Не удалось скачать аудио с YouTube (yt-dlp): The read operation timed out"
    assert _classify_youtube_import_error(msg) is None
    assert _is_non_retryable_import_error(msg) is False
