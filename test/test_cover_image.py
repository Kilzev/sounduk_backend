from io import BytesIO

from PIL import Image

from cover_image import normalize_cover_bytes


def _png_bytes(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (30, 80, 200))
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_normalize_cover_bytes_webp_and_square_cap():
    body, content_type = normalize_cover_bytes(_png_bytes(2000, 1200), max_side=1000)
    assert content_type == "image/webp"
    assert body[:4] == b"RIFF"
    decoded = Image.open(BytesIO(body))
    assert decoded.size[0] == decoded.size[1]
    assert decoded.size[0] <= 1000


def test_normalize_cover_bytes_pad_keeps_banner_without_cropping():
    body, _ = normalize_cover_bytes(_png_bytes(300, 80), square="pad")
    decoded = Image.open(BytesIO(body))
    assert decoded.size == (300, 300)
