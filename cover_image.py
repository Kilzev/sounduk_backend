"""Normalize cover images for S3: square crop, max side, WebP."""
from __future__ import annotations

from io import BytesIO

COVER_MAX_SIDE = 1000
WEBP_QUALITY = 80


def normalize_cover_bytes(
    data: bytes,
    *,
    max_side: int = COVER_MAX_SIDE,
    quality: int = WEBP_QUALITY,
) -> tuple[bytes, str]:
    """Return (body, content_type). Falls back to original JPEG bytes if decode fails."""
    if not data:
        raise ValueError("empty cover")

    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data, "image/jpeg"

    try:
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
        image.load()
    except Exception:
        return data, "image/jpeg"

    if image.mode in {"P", "PA"}:
        image = image.convert("RGBA")
    if image.mode == "RGBA":
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode != "RGB":
        image = image.convert("RGB")

    width, height = image.size
    if width > 0 and height > 0 and width != height:
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        image = image.crop((left, top, left + side, top + side))

    side = image.size[0]
    if side > max_side:
        image = image.resize((max_side, max_side), Image.Resampling.LANCZOS)

    out = BytesIO()
    try:
        image.save(out, format="WEBP", quality=quality, method=4)
        body = out.getvalue()
        if body:
            return body, "image/webp"
    except Exception:
        pass

    jpeg_out = BytesIO()
    image.save(jpeg_out, format="JPEG", quality=max(quality, 85), optimize=True)
    return jpeg_out.getvalue(), "image/jpeg"
