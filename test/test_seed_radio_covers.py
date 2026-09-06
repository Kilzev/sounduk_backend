from seed_radio_covers import (
    html_image_urls,
    index_record_logo_urls,
    myradio24_user_id,
    somafm_cover_url,
    stream_path_basename,
)


def test_stream_path_basename():
    assert (
        stream_path_basename("https://radiorecord.hostingradio.ru/rr_main96.aacp")
        == "rr_main96.aacp"
    )
    assert stream_path_basename("") is None


def test_myradio24_user_id():
    assert myradio24_user_id("http://listen1.myradio24.com:9000/5967") == "5967"
    assert myradio24_user_id("https://myradio24.org/2666") == "2666"
    assert myradio24_user_id("https://radiorecord.hostingradio.ru/rr_main96.aacp") is None


def test_somafm_cover_url():
    assert somafm_cover_url("SomaFM: Groove Salad") == (
        "https://somafm.com/img3/groovesalad-400.jpg"
    )
    assert somafm_cover_url("Jazz FM 89.1") is None


def test_index_record_logo_urls_maps_stream_files():
    payload = {
        "result": {
            "stations": [
                {
                    "icon_fill_colored": "https://www.radiorecord.ru/upload/stations_images/record_image600_colored_fill.png",
                    "stream_320": "https://radiorecord.hostingradio.ru/rr_main96.aacp",
                    "stream_64": "https://radiorecord.hostingradio.ru/rr_main32.aacp",
                    "stream_hls": "https://hls-01-radiorecord.hostingradio.ru/record/playlist.m3u8",
                }
            ]
        }
    }
    index = index_record_logo_urls(payload)
    assert "playlist.m3u8" not in index
    assert "rr_main96.aacp" in index


def test_html_image_urls_prefers_og_and_apple_touch():
    html = """
    <link rel="icon" sizes="16x16" href="/favicon-16.png">
    <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
    <meta property="og:image" content="https://cdn.example/logo-1000.png">
    """
    urls = html_image_urls(html, "https://example.com/")
    assert urls[0] == "https://cdn.example/logo-1000.png"
    assert "https://example.com/apple-touch-icon.png" in urls
